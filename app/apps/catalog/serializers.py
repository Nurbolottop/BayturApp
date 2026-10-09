from apps.cashback.calc import round_half_up
from apps.common.i18n import tr
from apps.common.media import absolute_media_url
from apps.common.models import ProgramSettings


def cashback_preview(item, now=None, ps=None):
    """Баллы за оплату деньгами по цене по умолчанию — по базовой ставке (Бронза), без ДР и надбавки уровня."""
    from decimal import Decimal
    ps = ps or ProgramSettings.get()
    promo = item.promo_rate(now)
    rate = max(Decimal(ps.base_cashback_rate), Decimal(promo) if promo is not None else Decimal(0))
    return round_half_up(Decimal(item.price) * rate)  # баллы за деньги; курс оплаты баллами не участвует


def pricing_payload(item):
    p = dict(item.pricing or {})
    lo, hi = item.pricing_bounds()
    if item.pricing_type == 'check':
        return {'type': 'check', 'min': lo, 'max': hi}
    return {'type': 'unit', 'unit': p.get('unit', 'visit'), 'min': lo, 'max': hi}


def item_payload(item, now=None, ps=None):
    promo = item.promo_rate(now)
    gallery = [absolute_media_url(u) for u in ([item.image] if item.image else []) + list(item.gallery or [])
               if u]
    seen, uniq = set(), []
    for u in gallery:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return {
        'id': item.id,
        'category': item.category_id,
        'title': tr(item.title),
        'meta': tr(item.meta) or '',
        'image': absolute_media_url(item.image),
        'gallery': uniq,
        'price': item.price,
        'pricing': pricing_payload(item),
        'promoRate': float(promo) if promo is not None else None,
        'tag': tr(item.current_tag(now)) or None,
        'description': tr(item.description) or '',
        'features': [{'icon': f.get('icon'), 'text': tr(f.get('text'))} for f in (item.features or [])],
        'outlet': item.outlet_id,
        'isActive': item.is_active,
        'cashbackPreview': cashback_preview(item, now, ps),
    }


def rules_payload(category):
    # rate — единая базовая ставка (без надбавки уровня); точная ставка клиента — в /cashback-requests/quote
    return {
        'rate': float(ProgramSettings.get().base_cashback_rate),
        'maxPointsShare': 1.0,  # устарело: лимита доли нет, баллами — только вся сумма
        'methods': list(category.methods),
    }


def category_payload(category, items, now=None, ps=None):
    return {
        'id': category.id,
        'title': tr(category.title),
        'cover': absolute_media_url(category.cover),
        'sortOrder': category.sort_order,
        'rules': rules_payload(category),
        'items': [item_payload(i, now, ps) for i in items],
    }
