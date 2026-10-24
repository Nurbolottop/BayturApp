from io import StringIO

from django.core.management import call_command
from django.test import Client

from apps.catalog.models import Item, Venue
from apps.common.testing import BaseAPITestCase

SK = {'HTTP_X_BAYTUR_APP': 'sk'}


class BillsLiveTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        call_command('load_venues', stdout=StringIO())

    def services(self, mode):
        return self.api.get('/api/v1/services', **SK, HTTP_X_BAYTUR_MODE=mode).json()

    def test_bill_in_menus(self):
        from apps.catalog.models import Category
        Category.objects.filter(pk='food').update(client_orders=True)  # тест клиентской заявки на ресторане
        for mode, section, bill in (('ski', 'cafe', 'ski-cafe-bill'), ('ski', 'bar', 'ski-bar-bill'),
                                    ('kymyz', 'kymyz', 'kymyz-kymyz-bill')):
            sec = next(s for s in self.services(mode)['sections'] if s['id'] == section)
            first = sec['groups'][0]['items'][0]                         # «Счёт» — первым в разделе
            self.assertEqual((first['id'], first['action'], first['price'], first['pricing']['type']),
                             (bill, 'pay_cashier', None, 'check'))
            self.assertIn('points', first['methods'])
        member = self.make_member('+996555121212')
        self.auth(member)
        r = self.api.post('/api/v1/cashback-requests/quote', {'itemId': 'ski-cafe-bill', 'checkAmount': 1850},
                          format='json')
        self.assertEqual((r.status_code, r.json()['total']), (200, 1850), r.content)

    def test_from_price_only_rooms(self):
        sec = next(s for s in self.services('kymyz')['sections'] if s['id'] == 'stay')
        rooms = [i['price'] for g in sec['groups'] for i in g['items'] if 'extra-bed' not in i['id']
                 and 'kids' not in i['id'] and i['unit'] == 'night']
        self.assertEqual(sec['fromPrice'], min(rooms))
        self.assertFalse(Item.objects.get(pk='kymyz-full-lux-extra-bed').in_from_price)

    def test_live_summary(self):
        d = self.api.get('/api/v1/showcase', **SK, HTTP_X_BAYTUR_MODE='ski').json()
        self.assertEqual((d['live'], d['liveUpdatedAt']), ([], None))
        c = Client()
        c.force_login(self.make_staff('owner', superuser=True))
        page = c.get('/panel/catalog/venues/ski/')
        self.assertContains(page, 'Живая сводка')
        form = page.context['form']
        import json
        r = c.post('/panel/catalog/venues/ski/', {
            **{f'{f}_{lang}': (form.initial.get(f) or {}).get(lang, '') for f in ('name', 'short', 'place', 'description',
                                                                            'address') for lang in ('ru', 'ky', 'en')},
            'cover': '', 'phone': '', 'whatsapp': '', 'email': '', 'maps_url': '', 'two_gis_url': '',
            'is_open': 'on', 'accent': '#4A90D9', 'contacts': '[]', 'info': json.dumps([]), 'sort_order': '1',
            'is_active': 'on',
            'live': json.dumps([{'value': {'ru': '−8°'}, 'title': {'ru': 'на склоне'}},
                                {'value': {'ru': '40 см'}, 'title': {'ru': 'снега'}}]),
            'seasons-TOTAL_FORMS': '0', 'seasons-INITIAL_FORMS': '0', 'app-min_version_ios': '0.1.0',
            'app-min_version_android': '0.1.0'})
        self.assertEqual(r.status_code, 302, r.content.decode()[:3000])
        venue = Venue.objects.get(pk='ski')
        self.assertTrue(venue.live_updated_at)
        d = self.api.get('/api/v1/showcase', **SK, HTTP_X_BAYTUR_MODE='ski').json()
        self.assertEqual(d['live'], [{'value': '−8°', 'title': 'на склоне'}, {'value': '40 см', 'title': 'снега'}])
        self.assertTrue(d['liveUpdatedAt'])
