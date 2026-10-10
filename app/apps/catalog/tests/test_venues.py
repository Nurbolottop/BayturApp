from io import StringIO

from django.core.management import call_command

from apps.catalog.models import Item, Outlet, Section, Venue
from apps.common.testing import BaseAPITestCase


def L(ru):
    return {'ru': ru, 'ky': ru, 'en': ru}


class VenueCatalogTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.venue = Venue.objects.create(
            id='ski', name=L('Тоо-Ашуу'), sort_order=1,
            contacts=[{'label': L('Ресепшен'), 'phone': '+996 555 444 242', 'whatsapp': True}],
            info=[{'title': L('Трассы'), 'rows': [{'label': L('Трасса 1'), 'value': L('2,6 км · 32°')}]},
                  {'title': L('Как добраться'), 'text': L('120 км от Бишкека')}])
        Outlet.objects.create(id='ski-cafe', venue=self.venue, name=L('Кафе'))
        self.cafe = Section.objects.create(id='ski-cafe', venue=self.venue, category_id='food', title=L('Кафе'))
        self.soups = Section.objects.create(id='ski-cafe-soups', venue=self.venue, parent=self.cafe,
                                            category_id='food', title=L('Супы'))
        Section.objects.create(id='ski-empty', venue=self.venue, category_id='sport', title=L('Пусто'))
        self.borsch = Item.objects.create(
            id='ski-borsch', venue=self.venue, section=self.soups, category_id='food', outlet_id='ski-cafe',
            title=L('Борщ'), price=320, pricing={'type': 'unit', 'unit': 'visit', 'min': 1, 'max': 20},
            price_note=L('порция'))

    def test_venues_list_and_detail(self):
        d = self.api.get('/api/v1/venues').json()
        self.assertEqual([v['id'] for v in d], ['resort', 'ski'])
        v = self.api.get('/api/v1/venues/ski').json()
        self.assertEqual(v['contacts'][0], {'label': 'Ресепшен', 'phone': '+996 555 444 242', 'whatsapp': True,
                                            'email': None})
        self.assertEqual(v['info'][0]['rows'][0], {'label': 'Трасса 1', 'value': '2,6 км · 32°'})
        self.assertEqual(v['info'][1]['text'], '120 км от Бишкека')
        self.assertEqual(self.api.get('/api/v1/venues/nope').status_code, 404)

    def test_venue_catalog_tree(self):
        d = self.api.get('/api/v1/venues/ski/catalog').json()
        self.assertEqual(d['venue']['id'], 'ski')
        self.assertEqual([s['id'] for s in d['sections']], ['ski-cafe'])  # пустой подраздел не отдаётся
        soups = d['sections'][0]['sections'][0]
        self.assertEqual((soups['id'], soups['category']), ('ski-cafe-soups', 'food'))
        item = soups['items'][0]
        self.assertEqual((item['id'], item['price'], item['priceNote'], item['venue'], item['section']),
                         ('ski-borsch', 320, 'порция', 'ski', 'ski-cafe-soups'))
        self.assertIn('cash', soups['rules']['methods'])

    def test_legacy_catalog_only_baytur(self):
        ids = [i['id'] for c in self.api.get('/api/v1/catalog').json() for i in c['items']]
        self.assertTrue(ids)
        self.assertNotIn('ski-borsch', ids)
        self.assertTrue(all(Item.objects.get(pk=i).venue_id == 'resort' for i in ids))

    def test_new_venue_item_works_in_cashback_quote(self):
        member = self.make_member('+996555303030')
        self.auth(member)
        r = self.api.post('/api/v1/cashback-requests/quote', {'itemId': 'ski-borsch', 'quantity': 2}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['total'], 640)

    def test_panel_pages(self):
        from django.test import Client
        c = Client()
        c.force_login(self.make_staff('owner'))
        for url in ('/panel/catalog/', '/panel/catalog/?venue=ski', '/panel/catalog/venues/ski/',
                    '/panel/catalog/sections/ski-cafe-soups/', '/panel/catalog/sections/new/?venue=ski',
                    '/panel/catalog/items/ski-borsch/', '/panel/catalog/items/new/?section=ski-cafe-soups'):
            r = c.get(url)
            self.assertEqual(r.status_code, 200, url)
        self.assertContains(c.get('/panel/catalog/?venue=ski'), 'Борщ')

    def test_admin_api(self):
        api = self.staff_client(self.make_staff('owner'))
        r = api.get('/api/v1/admin/sections?venue=ski&parent=root')
        self.assertEqual(r.status_code, 200, r.content)
        r = api.get('/api/v1/admin/items?venue=ski')
        items = r.json().get('items', r.json())
        self.assertEqual([i['id'] for i in items], ['ski-borsch'])
        self.assertEqual(items[0]['priceNote']['ru'], 'порция')
        r = api.patch('/api/v1/admin/sections/ski-cafe-soups', {'parent': 'ski-cafe-soups'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class LoadVenuesTests(BaseAPITestCase):
    def test_load_is_create_only_and_valid(self):
        from apps.catalog import venues_data as D
        call_command('load_venues', stdout=StringIO())
        self.assertEqual(Item.objects.filter(venue__in=[v['id'] for v in D.VENUES]).count(), len(D.ITEMS))
        # правка из админки не перезаписывается повторной загрузкой
        item = Item.objects.get(pk=D.ITEMS[0]['id'])
        item.price = 1
        item.save()
        call_command('load_venues', stdout=StringIO())
        item.refresh_from_db()
        self.assertEqual(item.price, 1)
        for v in D.VENUES:
            r = self.api.get(f"/api/v1/venues/{v['id']}/catalog")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()['sections'])
