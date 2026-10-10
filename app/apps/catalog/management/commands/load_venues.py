"""
Объекты экосистемы, их прайс и акции (apps.catalog.venues_data): «Тоо-Ашуу», кымызолечение в Суусамыре.
Только создаёт отсутствующее — правки из админки не перезаписываются (как seed без --reset).
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Загрузить объекты, точки, подразделы и услуги из venues_data (только отсутствующие)'

    def handle(self, *args, **opts):
        from apps.catalog import venues_data as D
        from apps.catalog.models import Item, Outlet, Section, Venue
        from apps.common.caching import bump_content_version

        created = {'venues': 0, 'outlets': 0, 'sections': 0, 'items': 0}

        def add(model, key, pk, defaults):
            _, new = model.objects.get_or_create(pk=pk, defaults=defaults)
            created[key] += int(new)

        with transaction.atomic():
            for v in D.VENUES:
                add(Venue, 'venues', v['id'], {k: v.get(k, d) for k, d in (
                    ('name', {}), ('short', {}), ('description', {}), ('address', {}), ('contacts', []),
                    ('info', []), ('sort_order', 0))})
            for o in D.OUTLETS:
                add(Outlet, 'outlets', o['id'], {'venue_id': o['venue'], 'name': o['name'],
                                                 'sort_order': o.get('sort_order', 0)})
            # родители раньше детей
            for s in sorted(D.SECTIONS, key=lambda s: s.get('parent') is not None):
                add(Section, 'sections', s['id'], {
                    'venue_id': s['venue'], 'parent_id': s.get('parent'), 'category_id': s['category'],
                    'title': s['title'], 'note': s.get('note') or {}, 'sort_order': s.get('sort_order', 0)})
            for i in D.ITEMS:
                add(Item, 'items', i['id'], {
                    'venue_id': i['venue'], 'section_id': i['section'], 'outlet_id': i.get('outlet'),
                    'category_id': i['category'], 'title': i['title'], 'meta': i.get('meta') or {},
                    'price': i['price'], 'pricing': i['pricing'], 'price_note': i.get('price_note') or {},
                    'features': i.get('features') or [], 'description': i.get('description') or {},
                    'tag': i.get('tag') or {}, 'sort_order': i.get('sort_order', 0),
                    'season_from': date.fromisoformat(i['season_from']) if i.get('season_from') else None,
                    'season_to': date.fromisoformat(i['season_to']) if i.get('season_to') else None})
            from apps.catalog.models import Promotion
            created['promotions'] = 0
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
