from io import StringIO

from django.core.management import call_command
from django.test import Client

from apps.common.models import ProgramSettings
from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Privilege

SK = {'HTTP_X_BAYTUR_APP': 'sk'}


def set_sk_mode(value):
    ps = ProgramSettings.get()
    ps.sk_mode = value
    ps.save()


class ForcedSeasonTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        call_command('load_venues', stdout=StringIO())

    def test_forced_season_for_all_users(self):
        set_sk_mode('kymyz')
        r = self.api.get('/api/v1/showcase', **SK, HTTP_X_BAYTUR_MODE='ski')   # выбор пользователя не действует
        self.assertEqual((r.json()['mode'], r['X-Baytur-Mode']), ('kymyz', 'kymyz'))
        d = self.api.get('/api/v1/app/config', **SK).json()
        self.assertEqual((d['mode'], d['season'], d['seasonLocked']), ('kymyz', 'summer', True))
        self.assertEqual(self.api.get('/api/v1/services').json()['mode'], 'resort')   # bayturapp не затронут
        self.assertEqual(self.api.get('/api/v1/services', **SK, HTTP_X_BAYTUR_MODE='resort').status_code, 400)
        set_sk_mode('')
        d = self.api.get('/api/v1/app/config', **SK, HTTP_X_BAYTUR_MODE='ski').json()
        self.assertEqual((d['mode'], d['seasonLocked']), ('ski', False))

    def test_panel_switch(self):
        c = Client()
        c.force_login(self.make_staff('owner'))
        self.assertContains(c.get('/panel/catalog/'), 'Сезон для всех пользователей')
        r = c.post('/panel/sk-season/', {'sk_mode': 'ski', 'next': '/panel/catalog/'})
        self.assertEqual((r.status_code, r['Location']), (302, '/panel/catalog/'))
        self.assertEqual(ProgramSettings.get().sk_mode, 'ski')
        c.post('/panel/sk-season/', {'sk_mode': 'nope'})
        self.assertEqual(ProgramSettings.get().sk_mode, 'ski')
        c.post('/panel/sk-season/', {'sk_mode': ''})
        self.assertEqual(ProgramSettings.get().sk_mode, '')


class ModePrivilegesTests(BaseAPITestCase):
    def test_load_and_group(self):
        call_command('load_venues', stdout=StringIO())
        before = Privilege.objects.count()
        call_command('load_mode_privileges', stdout=StringIO())
        created = Privilege.objects.count() - before
        self.assertGreater(created, 0)
        call_command('load_mode_privileges', stdout=StringIO())                  # повторно — ничего нового
        self.assertEqual(Privilege.objects.count() - before, created)
        self.assertTrue(Privilege.objects.filter(modes=['ski']).exists())
        self.assertTrue(Privilege.objects.filter(modes=['kymyz']).exists())
        self.assertFalse(Privilege.objects.filter(modes=[]).exclude(group='birthday').exists())
        for p in Privilege.objects.filter(modes__contains=['ski']):
            self.assertTrue(p.title['ky'] and p.title['en'] and p.description['ru'])
        program = self.api.get('/api/v1/loyalty/program').json()['privileges']
        row = next(p for p in program if p['modes'] == ['kymyz'])
        self.assertTrue(row['modeTitle'].startswith('Только '))
        c = Client()
        c.force_login(self.make_staff('owner'))
        for url in ('/panel/tiers/', '/panel/tiers/?obj=all', '/panel/tiers/?obj=ski',
                    '/panel/tiers/privileges/new/?tier=gold&mode=kymyz'):
            self.assertEqual(c.get(url).status_code, 200, url)
        self.assertContains(c.get('/panel/tiers/?obj=ski'), 'Подъёмник без очереди')
        self.assertNotContains(c.get('/panel/tiers/?obj=ski'), 'Пиала кымыза')
