from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import Client

from apps.catalog.models import AppRelease, EternalNews, Item, Promotion, Season, Showcase, Venue
from apps.catalog.modes import active_sk_mode
from apps.common.testing import BaseAPITestCase
from apps.content.models import Promo, PublishStatus

SK = {'HTTP_X_BAYTUR_APP': 'sk'}


def L(ru):
    return {'ru': ru, 'ky': ru, 'en': ru}


class ModesApiTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        call_command('load_venues', stdout=StringIO())

    def get(self, url, **headers):
        return self.api.get(f'/api/v1{url}', **headers)

    def test_mode_resolution_and_headers(self):
        r = self.get('/showcase')
        self.assertEqual((r.status_code, r['X-Baytur-Mode']), (200, 'resort'))
        self.assertIn('X-Baytur-Mode', r['Vary'])
        r = self.get('/showcase', HTTP_X_BAYTUR_APP='sk', HTTP_X_BAYTUR_MODE='kymyz')
        self.assertEqual((r.json()['mode'], r.json()['season']), ('kymyz', 'summer'))
        self.assertEqual(self.get('/showcase', HTTP_X_BAYTUR_MODE='ski').json()['error']['code'], 'mode_not_allowed')
        self.assertEqual(self.get('/services', HTTP_X_BAYTUR_APP='sk', HTTP_X_BAYTUR_MODE='resort').status_code, 400)
        self.assertEqual(self.get('/services', HTTP_X_BAYTUR_APP='nope').status_code, 400)

    def test_season_switch_by_dates(self):
        self.assertEqual(active_sk_mode(date(2026, 6, 1)), 'kymyz')
        self.assertEqual(active_sk_mode(date(2027, 1, 10)), 'ski')
        self.assertEqual(active_sk_mode(date(2026, 10, 11)), 'ski')          # межсезонье → ближайший сезон
        Season.objects.filter(venue_id='ski', year=2026).update(off_season_mode='kymyz')
        self.assertEqual(active_sk_mode(date(2026, 10, 11)), 'kymyz')        # выбрано в админке
        # смена дат в админке переключает приложение без обновления
        Season.objects.filter(venue_id='kymyz', year=2026).update(starts_at=date(2026, 9, 1), ends_at=date(2026, 11, 1))
        self.assertEqual(active_sk_mode(date(2026, 10, 11)), 'kymyz')

    def test_app_config(self):
        d = self.get('/app/config').json()
        self.assertEqual(d['mode'], 'resort')
        self.assertNotIn('seasons', d)
        AppRelease.objects.filter(app='sk').update(maintenance=True, min_version_ios='2.0.0')
        d = self.get('/app/config', **SK, HTTP_X_BAYTUR_MODE='ski').json()
        self.assertEqual((d['mode'], d['season'], d['maintenance'], d['minVersion']['ios']), ('ski', 'winter', True,
                                                                                             '2.0.0'))
        self.assertTrue({'mode', 'startsAt', 'endsAt'} <= set(d['seasons'][0]))
        self.assertIn('pointsPerSom', d)
        self.assertFalse(self.get('/app/config').json()['maintenance'])     # у Resort свои техработы

    def test_modes_and_contacts(self):
        modes = {m['id']: m for m in self.get('/modes').json()}
        self.assertEqual(set(modes), {'resort', 'ski', 'kymyz'})
        c = self.get('/resort/contacts', **SK, HTTP_X_BAYTUR_MODE='kymyz').json()
        self.assertEqual(c['phone'], Venue.objects.get(pk='kymyz').phone or None)

    def test_services_tree(self):
        d = self.get('/services', **SK, HTTP_X_BAYTUR_MODE='ski').json()
        self.assertEqual(d['mode'], 'ski')
        kinds = {s['id']: s['kind'] for s in d['sections']}
        self.assertIn('info', kinds.values())
        section = next(s for s in d['sections'] if s['groups'])
        service = section['groups'][0]['items'][0]
        self.assertTrue({'id', 'price', 'unit', 'action', 'methods', 'cashbackPreview'} <= set(service))
        detail = self.get(f"/services/{service['id']}", **SK).json()
        self.assertEqual(detail['id'], service['id'])
        self.assertEqual(self.get('/services/nope').status_code, 404)
        resort = self.get('/services').json()
        self.assertEqual(resort['mode'], 'resort')
        ids = {s['id'] for sec in resort['sections'] for g in sec['groups'] for s in g['items']}
        self.assertFalse(any(i.startswith(('ski-', 'kymyz-')) for i in ids))
        # курорт — старый каталог: разделы программы как разделы услуг, все позиции курорта на месте
        rooms = next(s for s in resort['sections'] if s['id'] == 'rooms')
        self.assertEqual(rooms['kind'], 'stay')
        self.assertEqual(ids, set(Item.objects.active().filter(venue_id='resort').values_list('id', flat=True)))

    def test_showcase_and_eternal(self):
        Promotion.objects.filter(title__ru='Трансфер по суперцене').update(show_on_home=True)
        EternalNews.objects.create(about_id='kymyz', show_in=['ski'], title=L('Лето в Суусамыре'),
                                   slides=[{'image': '', 'title': L('Кымыз'), 'text': L('…'), 'cta': None}],
                                   early_bonus={'kind': 'points', 'value': 500, 'text': L('+500')})
        d = self.get('/showcase', **SK, HTTP_X_BAYTUR_MODE='ski').json()
        self.assertTrue(d['tiles'] and d['facts'])
        self.assertEqual(d['eternal']['about'], 'kymyz')
        self.assertEqual(d['eternal']['earlyBonus']['value'], 500)
        self.assertIsNone(self.get('/showcase', **SK, HTTP_X_BAYTUR_MODE='kymyz').json()['eternal'])
        self.assertEqual(self.get('/content/eternal', **SK, HTTP_X_BAYTUR_MODE='ski').status_code, 200)

    def test_content_filtered_by_mode(self):
        from apps.content.models import Article
        a = Article.objects.create(id='ski-open', title=L('Открытие'), status=PublishStatus.PUBLISHED,
                                   modes=['ski'])
        Promo.objects.create(article=a, status=PublishStatus.PUBLISHED, modes=['ski'])
        resort = [p['article']['id'] for p in self.get('/content/promos').json()]
        self.assertNotIn('ski-open', resort)
        ski = [p['article']['id'] for p in self.get('/content/promos', **SK, HTTP_X_BAYTUR_MODE='ski').json()]
        self.assertEqual(ski, ['ski-open'])

    def test_program_privilege_modes(self):
        from apps.loyalty.models import Privilege
        p = Privilege.objects.first()
        if p is None:
            self.skipTest('нет привилегий в сиде')
        p.modes = ['ski']
        p.save()
        row = next(x for x in self.get('/loyalty/program').json()['privileges'] if x['id'] == p.id)
        self.assertEqual((row['modes'], row['modeTitle']), (['ski'], 'Только Тоо-Ашуу'))


class ModesPanelTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        call_command('load_venues', stdout=StringIO())
        self.c = Client()
        self.c.force_login(self.make_staff('owner'))

    def test_switcher_and_pages(self):
        r = self.c.get('/panel/catalog/')
        self.assertContains(r, 'mode-bar')
        r = self.c.get('/panel/mode/ski/?section=catalog')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/panel/catalog/?mode=ski')
        r = self.c.get('/panel/catalog/')                                   # выбор запомнен в сессии
        self.assertContains(r, Item.objects.filter(venue_id='ski').first().title['ru'])
        for url in ('/panel/venue/', '/panel/catalog/venues/ski/', '/panel/showcase/', '/panel/eternal/',
                    '/panel/promotions/', '/panel/content/'):
            r = self.c.get(url, follow=True)
            self.assertEqual(r.status_code, 200, url)
        self.assertEqual(self.c.get('/panel/mode/nope/').status_code, 403)

    def test_save_venue_seasons_and_eternal(self):
        self.c.get('/panel/mode/kymyz/')
        r = self.c.get('/panel/eternal/')
        self.assertEqual(r.status_code, 200)
        r = self.c.post('/panel/eternal/', {'about': 'ski', 'show_in': ['kymyz'], 'title_ru': 'Зима на Тоо-Ашуу',
                                            'slides': '[]', 'early_bonus': '', 'is_active': 'on'})
        self.assertEqual(r.status_code, 302, r.content.decode()[:3000])
        self.assertTrue(EternalNews.objects.filter(show_in__contains=['kymyz']).exists())
        sc = Showcase.objects.get(venue_id='kymyz')
        r = self.c.post('/panel/showcase/', {
            'facts': '[{"ru": "2 200 м"}]', 'cta_ru': 'Забронировать', 'cta_section': sc.cta_section,
            'tiles': '[]', 'news-TOTAL_FORMS': '0', 'news-INITIAL_FORMS': '0'})
        self.assertEqual(r.status_code, 302, r.content.decode()[:3000])
        sc.refresh_from_db()
        self.assertEqual(sc.facts, [{'ru': '2 200 м'}])

    def test_resort_hides_eternal(self):
        self.c.get('/panel/mode/resort/')
        self.assertNotContains(self.c.get('/panel/catalog/'), '/panel/eternal/')
