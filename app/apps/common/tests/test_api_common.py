from apps.common.i18n import parse_accept_language, tr
from apps.common.testing import BaseAPITestCase


class CommonApiTests(BaseAPITestCase):
    def test_error_format_and_language(self):
        r = self.api.get('/api/v1/wallet', HTTP_ACCEPT_LANGUAGE='en')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {'error': {'code': 'auth_required', 'message': 'Please sign in to continue'}})
        r = self.api.get('/api/v1/wallet', HTTP_ACCEPT_LANGUAGE='ky')
        self.assertEqual(r.json()['error']['message'], 'Улантуу үчүн кириңиз')

    def test_public_catalog_localized_and_etag(self):
        r = self.api.get('/api/v1/catalog', HTTP_ACCEPT_LANGUAGE='en')
        self.assertEqual(r.status_code, 200)
        cats = r.json()
        self.assertEqual([c['id'] for c in cats], ['rooms', 'spa', 'food', 'pools', 'sport'])
        self.assertEqual(cats[0]['title'], 'Rooms')
        self.assertEqual(cats[3]['rules']['methods'], ['cash', 'elqr'])
        item = next(i for i in cats[1]['items'] if i['id'] == 'spa-bochka')
        self.assertEqual(item['promoRate'], 0.14)
        self.assertEqual(item['cashbackPreview'], 350)   # 2 500 × 14 % (акция)
        self.assertTrue(item['image'].startswith('https://api.test/'))
        self.assertEqual(r['Cache-Control'], 'public, max-age=300')
        r2 = self.api.get('/api/v1/catalog', HTTP_ACCEPT_LANGUAGE='en', HTTP_IF_NONE_MATCH=r['ETag'])
        self.assertEqual(r2.status_code, 304)
        # изменение каталога сбрасывает кеш
        from apps.catalog.models import Item
        i = Item.objects.get(pk='spa-stone')
        i.price = 3600
        i.save()
        r3 = self.api.get('/api/v1/catalog', HTTP_ACCEPT_LANGUAGE='en', HTTP_IF_NONE_MATCH=r['ETag'])
        self.assertEqual(r3.status_code, 200)

    def test_public_endpoints_without_token(self):
        for url in ('/api/v1/loyalty/program', '/api/v1/content/promos', '/api/v1/content/events',
                    '/api/v1/content/stories', '/api/v1/resort/contacts', '/api/v1/legal', '/api/v1/app/config',
                    '/api/v1/content/articles/jazz-evening', '/api/v1/catalog/items/room-deluxe'):
            self.assertEqual(self.api.get(url).status_code, 200, url)
        program = self.api.get('/api/v1/loyalty/program').json()
        self.assertEqual([t['threshold'] for t in program['tiers']], [0, 200_000, 300_000, 900_000, 2_000_000, 3_000_000])
        # from — для старых версий: накопленная сумма порогов
        self.assertEqual([t['from'] for t in program['tiers']], [0, 200_000, 500_000, 1_400_000, 3_400_000, 6_400_000])
        self.assertEqual(len(program['privileges']), 21)
        late = next(p for p in program['privileges'] if p['group'] == 'late-checkout')
        self.assertEqual(late['groupTitle'], 'Поздний выезд')
        from apps.loyalty.models import Privilege
        Privilege.objects.filter(pk='bai-club-platinum').update(group_title={})
        from django.core.cache import cache
        cache.clear()  # программа кешируется
        club = next(p for p in self.api.get('/api/v1/loyalty/program').json()['privileges'] if p['id'] == 'bai-club-platinum')
        self.assertEqual(club['groupTitle'], 'Доступ в Bai Club')   # без названия группы — название привилегии
        self.assertEqual(len(self.api.get('/api/v1/content/promos').json()), 5)

    def test_bad_token_on_public_endpoint_is_ignored(self):
        self.api.credentials(HTTP_AUTHORIZATION='Bearer garbage')
        self.assertEqual(self.api.get('/api/v1/catalog').status_code, 200)
        self.assertEqual(self.api.get('/api/v1/wallet').json()['error']['code'], 'token_invalid')

    def test_update_required_and_maintenance(self):
        self.settings_obj(min_version_ios='1.2.0')
        r = self.api.get('/api/v1/catalog', HTTP_X_PLATFORM='ios', HTTP_X_APP_VERSION='1.1.9')
        self.assertEqual((r.status_code, r.json()['error']['code']), (426, 'update_required'))
        self.assertEqual(self.api.get('/api/v1/catalog', HTTP_X_PLATFORM='android',
                                      HTTP_X_APP_VERSION='0.1').status_code, 200)
        cfg = self.api.get('/api/v1/app/config', HTTP_X_PLATFORM='ios', HTTP_X_APP_VERSION='1.1.9').json()
        self.assertTrue(cfg['updateRequired'])
        self.settings_obj(maintenance=True, min_version_ios='0.0.0')
        self.assertEqual(self.api.get('/api/v1/catalog').status_code, 503)

    def test_resort_contacts(self):
        d = self.api.get('/api/v1/resort/contacts').json()
        self.assertEqual(set(d), {'phone', 'whatsapp', 'mapsUrl', 'termsUrl', 'privacyUrl', 'deletionUrl'})
        self.assertFalse(d['whatsapp'].startswith('+'))

    def test_openapi_schema(self):
        r = self.api.get('/api/v1/schema')
        self.assertEqual(r.status_code, 200)


class I18nTests(BaseAPITestCase):
    def test_accept_language(self):
        self.assertEqual(parse_accept_language('ky-KG,ru;q=0.8'), 'ky')
        self.assertEqual(parse_accept_language('de,en;q=0.5'), 'en')
        self.assertEqual(parse_accept_language('fr'), 'ru')
        self.assertEqual(parse_accept_language(None), 'ru')

    def test_fallback(self):
        self.assertEqual(tr({'ru': 'Номера', 'ky': '', 'en': 'Rooms'}, 'ky'), 'Номера')


class SeedSafetyTests(BaseAPITestCase):
    def test_rerun_keeps_admin_edits(self):
        import io

        from django.core.management import call_command

        from apps.catalog.models import Item
        Item.objects.filter(pk='room-deluxe').update(image='uploads/image/x.jpg', price=25000, sort_order=0)
        call_command('seed', stdout=io.StringIO())
        item = Item.objects.get(pk='room-deluxe')
        self.assertEqual((item.image, item.price, item.sort_order), ('uploads/image/x.jpg', 25000, 0))
        call_command('seed', '--reset', stdout=io.StringIO())
        self.assertEqual(Item.objects.get(pk='room-deluxe').price, 23000)
