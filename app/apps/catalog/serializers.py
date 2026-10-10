from apps.cashback.calc import active_methods, round_half_up
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


def item_payload(item, now=None, ps=None, promotions=None):
    from .promotions import active_promotions, item_promo_payload
    if promotions is None:
        promotions = active_promotions(now)
    promo_price, offers = item_promo_payload(item, promotions, now)
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
        'venue': item.venue_id,
        'section': item.section_id,
        'priceNote': tr(item.price_note) or None,
        'season': {'from': item.season_from.isoformat() if item.season_from else None,
                   'to': item.season_to.isoformat() if item.season_to else None}
        if (item.season_from or item.season_to) else None,
        'isActive': item.is_active,
        'cashbackPreview': cashback_preview(item, now, ps),
        # акция на цену: {basePrice, price, promotionId} — цена за единицу для всех гостей; null — без скидки
        'promo': promo_price,
        'promotions': offers,
    }


def rules_payload(category):
    # rate — единая базовая ставка (без надбавки уровня); точная ставка клиента — в /cashback-requests/quote
    return {
        'rate': float(ProgramSettings.get().base_cashback_rate),
        'maxPointsShare': 1.0,  # устарело: лимита доли нет, баллами — только вся сумма
        'methods': active_methods(category.methods),
    }


def category_payload(category, items, now=None, ps=None, promotions=None):
    return {
        'id': category.id,
        'title': tr(category.title),
        'cover': absolute_media_url(category.cover),
        'sortOrder': category.sort_order,
        'rules': rules_payload(category),
        'items': [item_payload(i, now, ps, promotions) for i in items],
    }


def _l10n_rows(rows):
    return [{'label': tr(r.get('label')), 'value': tr(r.get('value'))} for r in rows or []]


def venue_payload(venue):
    info = []
    for block in venue.info or []:
        entry = {'title': tr(block.get('title'))}
        if block.get('rows'):
            entry['rows'] = _l10n_rows(block['rows'])
        else:
            entry['text'] = tr(block.get('text'))
        info.append(entry)
    return {
        'id': venue.id,
        'name': tr(venue.name),
        'short': tr(venue.short) or '',
        'description': tr(venue.description) or '',
        'address': tr(venue.address) or '',
        'cover': absolute_media_url(venue.cover),
        'contacts': [{'label': tr(c.get('label')), 'phone': c.get('phone') or None,
                      'whatsapp': bool(c.get('whatsapp')), 'email': c.get('email') or None}
                     for c in venue.contacts or []],
        'info': info,
        'sortOrder': venue.sort_order,
    }


def section_payload(section, children_of, items_of, now=None, ps=None, promotions=None):
    """Подраздел с вложенными подразделами и услугами; пустые ветки не отдаются."""
    children = [section_payload(c, children_of, items_of, now, ps, promotions)
                for c in children_of.get(section.id, [])]
    children = [c for c in children if c['items'] or c['sections']]
    return {
        'id': section.id,
        'title': tr(section.title),
        'note': tr(section.note) or None,
        'category': section.category_id,
        'rules': rules_payload(section.category),
        'sections': children,
        'items': [item_payload(i, now, ps, promotions) for i in items_of.get(section.id, [])],
    }


def promotion_payload(p, items_in_venue):
    """Акция для экрана «Акции» объекта: условия, к каким услугам относится, подарок, состав пакета."""
    from .promotions import limit_left, promotion_brief
    data = promotion_brief(p, tr)
    data.update({
        'description': tr(p.description) or '',
        'scope': p.scope,
        'from': p.starts_at.isoformat() if p.starts_at else None,
        'weekdays': p.weekdays or [],
        'timeFrom': p.time_from.strftime('%H:%M') if p.time_from else None,
        'timeTo': p.time_to.strftime('%H:%M') if p.time_to else None,
        'itemIds': items_in_venue,
        'gift': {'itemId': p.gift_item_id, 'title': tr(p.gift_item.title)} if p.gift_item_id else None,
        'bundle': {'price': p.bundle_price, 'items': [{'itemId': i.pk, 'title': tr(i.title), 'price': i.price}
                                                      for i in p.bundle_items.all()]}
        if p.kind == 'bundle' else None,
        'left': limit_left(p),
    })
    return data
