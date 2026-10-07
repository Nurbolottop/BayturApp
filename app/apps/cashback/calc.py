"""
Расчёт оплаты и кешбека (ТЗ §5.2) — эталон, перенесённый из PaymentCalculator мобилки.

  total        = price × quantity (unit) | checkAmount (check)
  Оплата — «всё или ничего»: клиент платит либо целиком баллами, либо целиком деньгами.
  maxPointsSom = total, если баллов хватает на всю сумму (floor(available / pointsPerSom) ≥ total), иначе 0
  pointsSom    = 0 или total
  moneySom     = total − pointsSom;  points = pointsSom × pointsPerSom
  cashback     = round(moneySom × rate × pointsPerSom) — только с денежной части
  rate         = max(база 5 %, акция, база × множитель ДР) × (1 + надбавка уровня / 100)
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from apps.common.errors import ApiError


def floor_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def round_half_up(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_HALF_UP))


@dataclass
class Rules:
    rate: Decimal
    base_rate: Decimal
    max_points_share: Decimal
    methods: list
    points_per_som: int
    bonuses: list = field(default_factory=list)

    def snapshot(self):
        return {
            'rate': str(self.rate),
            'baseRate': str(self.base_rate),
            'maxPointsShare': str(self.max_points_share),
            'methods': list(self.methods),
            'pointsPerSom': self.points_per_som,
        }

    @classmethod
    def from_snapshot(cls, snap, bonuses=None):
        return cls(rate=Decimal(snap['rate']), base_rate=Decimal(snap.get('baseRate', snap['rate'])),
                   max_points_share=Decimal(snap['maxPointsShare']), methods=list(snap['methods']),
                   points_per_som=int(snap.get('pointsPerSom', 100)), bonuses=bonuses or [])


@dataclass
class Split:
    total: int
    max_points_som: int
    points_som: int
    points: int
    money_som: int
    rate: Decimal
    cashback: int

    def as_dict(self):
        return {
            'total': self.total,
            'pointsSom': self.points_som,
            'points': self.points,
            'moneySom': self.money_som,
            'rate': float(self.rate),
            'cashback': self.cashback,
        }


def in_birthday_window(birthday, on_date, days_before, days_after):
    if not birthday:
        return False
    for year in (on_date.year - 1, on_date.year, on_date.year + 1):
        try:
            bd = birthday.replace(year=year)
        except ValueError:  # 29 февраля в невисокосный год
            bd = date(year, 2, 28)
        if bd - timedelta(days=days_before) <= on_date <= bd + timedelta(days=days_after):
            return True
    return False


def tier_bonus_for(member):
    """(уровень, надбавка %) клиента — для формулы кешбека. Гость — базовый уровень без надбавки."""
    if member is None:
        return None, Decimal('0')
    from apps.loyalty.services import get_wallet
    tier = get_wallet(member).tier
    return tier, Decimal(tier.cashback_bonus if tier is not None else 0)


def resolve_rules(item, member, settings, at):
    """
    Ставка кешбека: база (единая для всех услуг, по умолчанию 10/200 = 5 %); акция услуги или ×N в день рождения
    заменяют её, если больше; затем надбавка уровня клиента: rate × (1 + надбавка / 100).
    Баллы = Сумма × rate × pointsPerSom (с денежной части).
    """
    from apps.common.i18n import tr
    from django.utils import timezone

    category = item.category
    base = Decimal(settings.base_cashback_rate)
    rate = base
    bonuses = []
    promo = item.active_promo(at)
    if promo is not None and Decimal(promo.rate) > rate:
        rate = Decimal(promo.rate)
        bonuses.append({'kind': 'promo', 'title': tr(promo.tag) or tr(item.tag) or None})
    if member is not None and in_birthday_window(member.birthday, timezone.localtime(at).date(),
                                                 settings.birthday_days_before, settings.birthday_days_after):
        bday_rate = (base * Decimal(settings.birthday_multiplier)).quantize(Decimal('0.0001'))
        if bday_rate > rate:
            rate = bday_rate
            bonuses = [{'kind': 'birthday', 'multiplier': float(settings.birthday_multiplier)}]
    tier, bonus = tier_bonus_for(member)
    if bonus:
        rate = (rate * (1 + bonus / 100)).quantize(Decimal('0.0001'))
        bonuses.append({'kind': 'tier', 'tierId': tier.pk, 'percent': float(bonus)})
    rate = min(rate, Decimal('1'))
    # Лимита доли по категориям больше нет: баллами можно оплатить любую услугу целиком
    return Rules(rate=rate, base_rate=base, max_points_share=Decimal('1'),
                 methods=list(category.methods), points_per_som=settings.points_per_som, bonuses=bonuses)


def compute_total(item, quantity, check_amount):
    lo, hi = item.pricing_bounds()
    if item.pricing_type == 'check':
        if check_amount is None or not (lo <= int(check_amount) <= hi):
            raise ApiError('amount_out_of_range', 422, extra={'min': lo, 'max': hi})
        return int(check_amount), 1
    quantity = 1 if quantity is None else int(quantity)
    if not (lo <= quantity <= hi):
        raise ApiError('amount_out_of_range', 422, extra={'min': lo, 'max': hi})
    return item.price * quantity, quantity


def balance_som(available, rules):
    return max(0, available) // rules.points_per_som


def max_points_som(total, rules, available):
    """Сколько можно оплатить баллами: вся сумма, если баланса хватает, иначе 0 (частичной оплаты нет)."""
    return total if balance_som(available, rules) >= total else 0


def compute_split(total, rules, available, requested_points_som, strict=False):
    """
    pointsSom > 0 означает «оплатить баллами целиком».
    strict=False — quote: pointsSom = total, если баллов хватает, иначе 0.
    strict=True  — создание заявки / правка суммы: частичная оплата → points_partial,
                   баллов не хватает на всю сумму → insufficient_points.
    """
    requested = max(0, int(requested_points_som or 0))
    limit = max_points_som(total, rules, available)
    if strict and requested:
        if requested != total:
            raise ApiError('points_partial', 422, extra={'total': total})
        if not limit:
            raise ApiError('insufficient_points', 422,
                           extra={'maxPointsSom': 0, 'shortSom': total - balance_som(available, rules)})
    points_som = total if requested and limit else 0
    money_som = total - points_som
    cashback = round_half_up(Decimal(money_som) * rules.rate * rules.points_per_som)
    return Split(total=total, max_points_som=limit, points_som=points_som,
                 points=points_som * rules.points_per_som, money_som=money_som, rate=rules.rate, cashback=cashback)
