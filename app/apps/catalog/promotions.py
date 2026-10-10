"""
Акции на цену: какая акция действует на услугу и сколько стоит заказ с ней.

best_price() — для расчёта (quote), онлайн-оплаты и заявки: базовая цена × количество → лучшая итоговая цена.
Несовместимая акция не сочетается ни с чем; совместимые применяются вместе (по порядку). Из двух вариантов —
лучшая несовместимая или все совместимые вместе — клиенту достаётся более выгодный.
Применяется к услугам с ценой за единицу; «по чеку» сумма — это уже оплаченный чек, акции к ней не применяются.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from .models import Promotion, PromotionAudience, PromotionKind, PromotionScope

FINAL_STATUSES_FREE = ('rejected', 'cancelled')  # такие заявки лимит акции не расходуют


def _round(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def is_active_at(p, at=None):
    at = timezone.localtime(at or timezone.now())
    if not p.is_active:
        return False
    if p.starts_at and at < p.starts_at:
        return False
    if p.ends_at and at >= p.ends_at:
        return False
    if p.weekdays and at.weekday() not in [int(d) for d in p.weekdays]:
        return False
    if p.time_from or p.time_to:
        t = at.time()
        lo, hi = p.time_from, p.time_to
        if lo and hi and lo > hi:  # через полночь: 22:00–02:00
            if not (t >= lo or t < hi):
                return False
        elif (lo and t < lo) or (hi and t >= hi):
            return False
    return True


def active_promotions(at=None):
    """Все включённые сейчас акции с охватом (id объектов, разделов, услуг) — одним запросом на каждое M2M."""
    at = at or timezone.now()
    qs = Promotion.objects.filter(is_active=True).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=at), Q(ends_at__isnull=True) | Q(ends_at__gt=at)) \
        .prefetch_related('venues', 'sections', 'items', 'bundle_items').select_related('gift_item')
    out = []
    for p in qs:
        if not is_active_at(p, at):
            continue
        p._venue_ids = {v.pk for v in p.venues.all()}
        p._section_ids = {s.pk for s in p.sections.all()}
        p._item_ids = {i.pk for i in p.items.all()}
        out.append(p)
    return out


def covers(p, item):
    if p.scope == PromotionScope.ALL:
        return True
    if p.scope == PromotionScope.VENUES:
        return item.venue_id in p._venue_ids
    if p.scope == PromotionScope.SECTIONS:
        section = item.section
        while section is not None:  # раздел целиком — вместе с вложенными подразделами
            if section.pk in p._section_ids:
                return True
            section = section.parent
        return False
    return item.pk in p._item_ids


def _tier_of(member):
    from apps.loyalty.services import get_wallet
    return get_wallet(member).tier_id


def audience_ok(p, member, quantity):
    if p.audience == PromotionAudience.MEMBERS:
        return member is not None
    if p.audience == PromotionAudience.TIERS:
        return member is not None and _tier_of(member) in (p.tiers or [])
    if p.audience == PromotionAudience.GROUPS:
        return quantity >= (p.group_min or 1)
    return True  # все гости; «дети» — акция настроена на детские услуги


def used(p):
    from apps.cashback.models import CashbackRequest
    return CashbackRequest.objects.filter(promotion__ids__contains=[p.pk]) \
        .exclude(status__in=FINAL_STATUSES_FREE).count()


def limit_left(p):
    return None if p.usage_limit is None else max(0, p.usage_limit - used(p))


def eligible(p, member, quantity, base_total, check_limit=True):
    if p.min_quantity and quantity < p.min_quantity:
        return False
    if p.min_amount and base_total < p.min_amount:
        return False
    if not audience_ok(p, member, quantity):
        return False
    return not (check_limit and p.usage_limit is not None and limit_left(p) <= 0)


def apply_one(p, unit_price, quantity, total):
    v = Decimal(p.value or 0)
    if p.kind == PromotionKind.PERCENT:
        return max(0, total - _round(Decimal(total) * v / 100))
    if p.kind == PromotionKind.AMOUNT:
        return max(0, total - _round(v))
    if p.kind == PromotionKind.SPECIAL_PRICE:
        return min(total, _round(v) * quantity)
    if p.kind == PromotionKind.N_PLUS_ONE:
        n = max(1, int(v))
        return max(0, total - unit_price * (quantity // (n + 1)))
    return total  # подарок и пакет цену заказа не меняют


def _snapshot(applied, base, total):
    gift = next((p.gift_item for p in applied if p.kind == PromotionKind.GIFT and p.gift_item_id), None)
    first = applied[0]
    return {
        'ids': [p.pk for p in applied],
        'id': first.pk,
        'title': first.title,
        'kind': first.kind,
        'basePrice': base,
        'total': total,
        'discount': base - total,
        'gift': {'itemId': gift.pk, 'title': gift.title} if gift else None,
    }


def best_price(item, quantity, member=None, at=None, promotions=None, check_limit=True):
    """→ (итоговая сумма, снимок применённой акции или None) для услуги с ценой за единицу."""
    base = item.price * quantity
    if item.pricing_type == 'check':
        return base, None
    candidates = [p for p in (promotions if promotions is not None else active_promotions(at))
                  if p.kind != PromotionKind.BUNDLE and covers(p, item)
                  and eligible(p, member, quantity, base, check_limit)]
    if not candidates:
        return base, None
    options = []
    for p in candidates:
        if not p.stackable:
            options.append((apply_one(p, item.price, quantity, base), [p]))
    stack = sorted((p for p in candidates if p.stackable), key=lambda p: (p.sort_order, p.pk))
    if stack:
        total = base
        for p in stack:
            total = apply_one(p, item.price, quantity, total)
        options.append((total, stack))
    # выгоднее — меньшая сумма; при равенстве — где есть подарок
    total, applied = min(options, key=lambda o: (o[0], not any(p.kind == PromotionKind.GIFT for p in o[1])))
    return total, _snapshot(applied, base, total)


# ---------------------------------------------------------------- для прайса

def item_promo_payload(item, promotions, now=None):
    """
    Для карточки услуги в прайсе: цена за 1 единицу с акцией для всех гостей (если есть) и список действующих
    акций с условиями — «для участников», «от 3 ночей», «третья ночь бесплатно».
    """
    from apps.common.i18n import tr
    covering = [p for p in promotions if covers(p, item)]
    if not covering:
        return None, []
    q = max(1, item.pricing_bounds()[0]) if item.pricing_type != 'check' else 1
    public = [p for p in covering if p.audience in (PromotionAudience.ALL, PromotionAudience.CHILDREN)
              and not p.min_quantity and not p.min_amount]
    total, snap = best_price(item, q, None, now, promotions=public, check_limit=True) \
        if item.pricing_type != 'check' else (item.price, None)
    price = None
    if snap and snap['discount'] > 0:
        price = {'basePrice': item.price, 'price': _round(Decimal(total) / q), 'promotionId': snap['id']}
    offers = [promotion_brief(p, tr) for p in covering]
    return price, offers


def promotion_brief(p, tr):
    return {
        'id': p.pk,
        'title': tr(p.title),
        'tag': tr(p.tag) or None,
        'kind': p.kind,
        'value': float(p.value or 0),
        'audience': p.audience,
        'tiers': p.tiers or [],
        'groupMin': p.group_min,
        'minQuantity': p.min_quantity,
        'minAmount': p.min_amount,
        'until': timezone.localtime(p.ends_at).isoformat() if p.ends_at else None,
        'stackable': p.stackable,
        'giftItemId': p.gift_item_id,
    }
