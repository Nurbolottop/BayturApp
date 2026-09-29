"""
Расчёт оплаты и кешбека (ТЗ §5.2) — эталон, перенесённый из PaymentCalculator мобилки.

  total        = price × quantity (unit) | checkAmount (check)
  maxPointsSom = max(0, min(floor(total × maxPointsShare), floor(available / pointsPerSom)))
  pointsSom    = запрошенное, ограниченное 0…maxPointsSom
  moneySom     = total − pointsSom;  points = pointsSom × pointsPerSom
  cashback     = round(moneySom × rate × pointsPerSom) — только с денежной части
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


def resolve_rules(item, member, settings, at):
    """Правила категории; promoRate акции заменяет rate; ДР — rate × множитель; берётся большая ставка."""
    from apps.common.i18n import tr
    from django.utils import timezone

    category = item.category
    base = Decimal(category.rate)
    rate = base
    bonuses = []
    promo = item.active_promo(at)
    if promo is not None:
        rate = Decimal(promo.rate)
        bonuses.append({'kind': 'promo', 'title': tr(promo.tag) or tr(item.tag) or None})
    if member is not None and in_birthday_window(member.birthday, timezone.localtime(at).date(),
                                                 settings.birthday_days_before, settings.birthday_days_after):
        bday_rate = (base * Decimal(settings.birthday_multiplier)).quantize(Decimal('0.0001'))
        if bday_rate > rate:
            rate = bday_rate
            bonuses = [{'kind': 'birthday', 'multiplier': float(settings.birthday_multiplier)}]
    rate = min(rate, Decimal('1'))
    return Rules(rate=rate, base_rate=base, max_points_share=Decimal(category.max_points_share),
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


def max_points_som(total, rules, available):
    by_share = floor_int(Decimal(total) * rules.max_points_share)
    by_balance = max(0, available) // rules.points_per_som
    return max(0, min(by_share, by_balance))


def compute_split(total, rules, available, requested_points_som, strict=False):
    """
    strict=False — quote: pointsSom тихо ограничивается 0…maxPointsSom.
    strict=True  — создание заявки: превышение → ошибка.
    """
    requested = max(0, int(requested_points_som or 0))
    limit = max_points_som(total, rules, available)
    if strict and requested > limit:
        by_share = floor_int(Decimal(total) * rules.max_points_share)
        if requested > by_share:
            raise ApiError('points_limit_exceeded', 422, extra={'maxPointsSom': limit})
        raise ApiError('insufficient_points', 422, extra={'maxPointsSom': limit})
    points_som = min(requested, limit)
    money_som = total - points_som
    cashback = round_half_up(Decimal(money_som) * rules.rate * rules.points_per_som)
    return Split(total=total, max_points_som=limit, points_som=points_som,
                 points=points_som * rules.points_per_som, money_som=money_som, rate=rules.rate, cashback=cashback)
