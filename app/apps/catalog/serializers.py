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


# ---------------------------------------------------------------- ТЗ экосистемы: режимы, витрина, услуги

def mode_payload(venue):
    """GET /modes: объект экосистемы для пометок в истории и привилегиях."""
    return {'id': venue.id, 'app': venue.app, 'title': tr(venue.name), 'subtitle': tr(venue.short) or '',
            'icon': absolute_media_url(venue.icon) or None}


def section_methods(section):
    """Способы оплаты раздела: свои → родительского раздела → раздела программы. + points («всё или ничего»)."""
    from apps.cashback.calc import active_methods
    methods = section.methods
    if methods is None and section.parent_id:
        methods = section.parent.methods
    if methods is None:
        methods = section.category.methods
    return list(active_methods(methods)) + ['points']


def service_methods(item):
    if item.methods is not None:
        from apps.cashback.calc import active_methods
        return list(active_methods(item.methods)) + ['points']
    if item.section_id:
        return section_methods(item.section)
    from apps.cashback.calc import active_methods
    return list(active_methods(item.category.methods)) + ['points']


def _showcase_promo(item, promotions, now):
    """Витринная акция на сегодня (ТЗ §5.4): {id, badge, note, price, oldPrice}; точная цена — в /quote."""
    from .promotions import item_promo_payload
    price, offers = item_promo_payload(item, promotions, now)
    if not offers:
        return None
    promo = next((p for p in promotions if p.pk == (price or {}).get('promotionId')), None) \
        or next(p for p in promotions if p.pk == offers[0]['id'])
    return {'id': promo.pk, 'badge': tr(promo.tag) or None, 'note': tr(promo.note) or None,
            'price': price['price'] if price else None, 'oldPrice': item.price if price else None}


def service_payload(item, kind='', promotions=None, now=None, ps=None):
    """Позиция прайса (ТЗ §4.3, §6.3)."""
    from django.utils import timezone as tz

    from .promotions import active_promotions
    now = now or tz.now()
    if promotions is None:
        promotions = active_promotions(now)
    today = tz.localdate(now)
    available = not ((item.season_from and today < item.season_from) or (item.season_to and today > item.season_to))
    photos = [absolute_media_url(u) for u in ([item.image] if item.image else []) + list(item.gallery or []) if u]
    lo, hi = item.pricing_bounds()
    return {
        'id': item.id,
        'mode': item.venue_id,
        'title': tr(item.title),
        'note': tr(item.meta) or None,
        'description': tr(item.description) or '',
        'includes': [tr(f.get('text')) for f in item.features or [] if tr(f.get('text'))],
        'photos': list(dict.fromkeys(photos)),
        'price': None if item.price_on_request else item.price,
        'priceUpTo': item.price_up_to,
        'unit': item.unit or 'none',
        'unitText': tr(item.price_note) or None,
        'pricing': {'type': item.pricing_type, 'min': lo, 'max': hi},
        'promo': _showcase_promo(item, promotions, now),
        'cashbackPreview': None if kind == 'menu' else cashback_preview(item, now, ps),
        'action': item.action,
        'methods': service_methods(item),
        'availableFrom': item.season_from.isoformat() if item.season_from else None,
        'availableTo': item.season_to.isoformat() if item.season_to else None,
        'available': available,
        'capacity': item.capacity,
        'featured': item.featured,
        'outletIds': [item.outlet_id] if item.outlet_id else [],
    }


def info_payload(block):
    lines = []
    for line in block.lines or []:
        slope = line.get('slopeDeg')
        lines.append({'title': tr(line.get('title')) or None, 'value': tr(line.get('value')) or None,
                      'phone': line.get('phone') or None, 'whatsapp': line.get('whatsapp') or None,
                      'level': round(min(1.0, max(0.0, float(slope) / 45.0)), 2) if slope else None})
    return {'id': block.pk, 'title': tr(block.title), 'lines': lines}


def services_section_payload(section, children, items_of, promotions, now, ps):
    from apps.common.models import ProgramSettings
    kind = section.kind or ''
    groups = []
    if items_of.get(section.id):  # позиции прямо в разделе — одна группа
        groups.append({'id': f'{section.key or section.id}-main', 'title': tr(section.title),
                       'items': [service_payload(i, kind, promotions, now, ps) for i in items_of[section.id]]})
    for child in children:
        items = items_of.get(child.id) or []
        if items:
            groups.append({'id': child.key or child.id, 'title': tr(child.title),
                           'items': [service_payload(i, kind, promotions, now, ps) for i in items]})
    all_items = [i for g in groups for i in g['items']]
    prices = [(i['promo'] or {}).get('price') or i['price'] for i in all_items
              if i['price'] is not None and ((i['promo'] or {}).get('price') or i['price'])]
    rate = section.cashback_rate if section.cashback_rate is not None else (ps or ProgramSettings.get()).base_cashback_rate
    return {
        'id': section.key or section.id,
        'kind': kind or None,
        'icon': section.icon or None,
        'title': tr(section.title),
        'subtitle': tr(section.subtitle) or None,
        'notice': tr(section.note) or None,
        'cover': absolute_media_url(section.cover),
        'fromPrice': min(prices) if prices else None,
        'hasPromo': any(i['promo'] for i in all_items),
        'rules': {'rate': float(rate), 'methods': section_methods(section)},
        'groups': groups,
        'info': [info_payload(b) for b in section.info_blocks.all()],
    }

