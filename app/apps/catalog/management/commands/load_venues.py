"""
Режимы S&K (ski — «Тоо-Ашуу», kymyz — кымызолечение в Суусамыре), их прайс, справка, главная, сезоны и акции
(apps.catalog.venues_data). Только создаёт отсутствующее — правки из админки не перезаписываются.
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction


def _date(value):
    return date.fromisoformat(value) if value else None


def item_unit(item, section_kind):
    """Единица из ТЗ §4.3 по типу цены и разделу."""
    unit = (item.get('pricing') or {}).get('unit')
    note = ((item.get('price_note') or {}).get('ru') or '').lower()
    if (item.get('pricing') or {}).get('type') == 'check':
        return 'none'
    if section_kind == 'transfer':
        if unit == 'guest':
            return 'seat'
        return 'vehicle_round_trip' if 'обратно' in note else 'vehicle_one_way'
    if section_kind == 'menu':
        return 'piece' if item['section'].startswith('ski-bar') else 'portion'
    if '3 час' in note:
        return 'hours3'
    if '30 мин' in note:
        return 'min30'
    return {'night': 'night', 'guest': 'person', 'session': 'session', 'hour': 'hour'}.get(unit, 'visit')


def item_action(section_kind):
    """Пока нет броней (этап 4 ТЗ): меню — справочно, остальное — оплата у кассира."""
    return 'info' if section_kind == 'menu' else 'pay_cashier'


class Command(BaseCommand):
    help = 'Загрузить режимы S&K, прайс, справку, главную, сезоны и акции (только отсутствующее)'

    def handle(self, *args, **opts):
        from apps.catalog import venues_data as D
        from apps.catalog.models import (AppRelease, InfoBlock, Item, Outlet, Promotion, Season, Section, Showcase,
                                         Venue)
        from apps.common.caching import bump_content_version

        created = dict.fromkeys(('venues', 'outlets', 'sections', 'items', 'info', 'seasons', 'showcases',
                                 'promotions'), 0)

        def add(model, key, pk, defaults):
            obj, new = model.objects.get_or_create(pk=pk, defaults=defaults)
            created[key] += int(new)
            return obj

        meta = {s['id']: getattr(D, 'SECTION_META', {}).get(s['id']) for s in D.SECTIONS}
        kinds = {}
        with transaction.atomic():
            AppRelease.objects.get_or_create(app='sk')
            for v in D.VENUES:
                m = getattr(D, 'MODES_META', {}).get(v['id'], {})
                add(Venue, 'venues', v['id'], {
                    'app': m.get('app', 'resort'), 'name': m.get('name') or v['name'],
                    'short': m.get('short') or v.get('short', {}), 'description': v.get('description', {}),
                    'address': v.get('address', {}), 'contacts': v.get('contacts', []), 'info': v.get('info', []),
                    'phone': m.get('phone', ''), 'whatsapp': m.get('whatsapp', ''), 'email': m.get('email', ''),
                    'accent': m.get('accent', '#C6F24E'), 'sort_order': v.get('sort_order', 0),
                    'early_booking_enabled': m.get('early_booking_enabled', False)})
            for o in D.OUTLETS:
                add(Outlet, 'outlets', o['id'], {'venue_id': o['venue'], 'name': o['name'],
                                                 'sort_order': o.get('sort_order', 0)})
            for s in sorted(D.SECTIONS, key=lambda s: s.get('parent') is not None):
                parent = s.get('parent')
                if parent:
                    key, kind, icon = s['id'][len(parent) + 1:], kinds.get(parent, ''), ''
                else:
                    key, kind, icon = meta.get(s['id']) or (s['id'].split('-', 1)[1], '', '')
                kinds[s['id']] = kind
                add(Section, 'sections', s['id'], {
                    'venue_id': s['venue'], 'parent_id': parent, 'category_id': s['category'], 'key': key,
                    'kind': kind, 'icon': icon, 'title': s['title'], 'note': s.get('note') or {},
                    'sort_order': s.get('sort_order', 0)})
            # справка — отдельный раздел kind=info из инфоблоков объекта
            for v in D.VENUES:
                info = getattr(D, 'INFO_SECTIONS', {}).get(v['id'])
                if not info:
                    continue
                section = add(Section, 'sections', info['id'], {
                    'venue_id': v['id'], 'category_id': 'sport', 'key': info['key'], 'kind': 'info',
                    'icon': info['icon'], 'title': info['title'], 'sort_order': 900})
                if section.info_blocks.exists():
                    continue
                for n, block in enumerate(v.get('info') or []):
                    lines = [{'title': r['label'], 'value': r['value'],
                              'slopeDeg': getattr(D, 'SLOPES', {}).get(r['label'].get('ru'))}
                             for r in block.get('rows') or []] or [{'title': {}, 'value': block.get('text') or {}}]
                    InfoBlock.objects.create(section=section, title=block['title'], lines=lines, sort_order=n)
                    created['info'] += 1
            for i in D.ITEMS:
                kind = kinds.get(i['section'], '')
                add(Item, 'items', i['id'], {
                    'venue_id': i['venue'], 'section_id': i['section'], 'outlet_id': i.get('outlet'),
                    'category_id': i['category'], 'title': i['title'], 'meta': i.get('meta') or {},
                    'price': i['price'], 'pricing': i['pricing'], 'price_note': i.get('price_note') or {},
                    'price_up_to': i['pricing'].get('max') if i['pricing'].get('type') == 'check' else None,
                    'unit': item_unit(i, kind), 'action': item_action(kind),
                    'features': i.get('features') or [], 'description': i.get('description') or {},
                    'tag': i.get('tag') or {}, 'sort_order': i.get('sort_order', 0),
                    'season_from': _date(i.get('season_from')), 'season_to': _date(i.get('season_to'))})
            for venue_id, sc in getattr(D, 'SHOWCASES', {}).items():
                if Showcase.objects.filter(venue_id=venue_id).exists():
                    continue
                Showcase.objects.create(venue_id=venue_id, facts=sc['facts'], cta=sc['cta'],
                                        cta_section=sc['cta_section'],
                                        tiles=[{'section': t[0], 'icon': t[1], 'title': t[2]} for t in sc['tiles']])
                created['showcases'] += 1
            for se in getattr(D, 'SEASONS', []):
                _, new = Season.objects.get_or_create(venue_id=se['venue'], year=se['year'], defaults={
                    'starts_at': _date(se['starts_at']), 'ends_at': _date(se['ends_at']),
                    'early_booking_from': _date(se.get('early_booking_from'))})
                created['seasons'] += int(new)
            for pr in getattr(D, 'PROMOTIONS', []):
                if Promotion.objects.filter(title__ru=pr['title']['ru']).exists():
                    continue
                promo = Promotion.objects.create(
                    title=pr['title'], description=pr.get('description') or {}, tag=pr.get('tag') or {},
                    kind=pr['kind'], value=pr.get('value', 0), scope=pr.get('scope', 'items'),
                    audience=pr.get('audience', 'all'), gift_item_id=pr.get('gift_item'))
                promo.items.set(pr.get('items', []))
                promo.venues.set(pr.get('venues', []))
                promo.sections.set(pr.get('sections', []))
                created['promotions'] += 1
        bump_content_version()
        self.stdout.write(self.style.SUCCESS(
            'Добавлено: ' + ', '.join(f'{k} {v}' for k, v in created.items()) + ' (существующие не тронуты)'))
