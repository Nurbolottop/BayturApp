from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import PERK_ICONS


class LegalPagesTests(BaseAPITestCase):
    def test_api_links_point_to_our_pages(self):
        data = self.api.get('/api/v1/legal', HTTP_ACCEPT_LANGUAGE='ky').json()
        self.assertEqual(data['privacy']['url'], 'https://api.test/legal/privacy?lang=ky')
        self.assertEqual(data['terms']['url'], 'https://api.test/legal/terms?lang=ky')
        contacts = self.api.get('/api/v1/resort/contacts', HTTP_ACCEPT_LANGUAGE='en').json()
        self.assertEqual(contacts['privacyUrl'], 'https://api.test/legal/privacy?lang=en')

    def test_pages_render_in_three_languages(self):
        for lang, needle in (('ru', 'Политика конфиденциальности'), ('en', 'privacy policy'),
                             ('ky', 'купуялуулук саясаты')):
            r = self.client.get(f'/legal/privacy?lang={lang}')
            self.assertContains(r, needle)
            self.assertContains(r, 'Freedom Pay')
            self.assertNotContains(r, '{phone}')
        r = self.client.get('/legal/terms?lang=ru')
        self.assertContains(r, '1 балл = 1 сом')
        self.assertContains(r, '<h2>Уровни</h2>', html=True)
        self.assertEqual(self.client.get('/legal/deletion').status_code, 404)

    def test_text_is_escaped(self):
        from apps.members.web import render_legal_text
        title, html = render_legal_text('Заголовок\n\n<script>x</script>\n- пункт', {})
        self.assertEqual(title, 'Заголовок')
        self.assertNotIn('<script>', html)
        self.assertIn('<li>пункт</li>', html)


class UpgraderPrivilegesTests(BaseAPITestCase):
    def test_21_privileges_grouped_with_rates_and_footnotes(self):
        program = self.api.get('/api/v1/loyalty/program').json()
        privileges = program['privileges']
        self.assertEqual(len(privileges), 21)
        self.assertTrue(all(p['icon'] in PERK_ICONS for p in privileges))
        rate = {p['tier']: p['title'] for p in privileges if p['group'] == 'points-rate'}
        self.assertEqual(rate['bronze'], 'Начисление 5% баллами')
        self.assertEqual(rate['gold'], 'Начисление 6,25% баллами')
        self.assertEqual(rate['ambassador'], 'Начисление 10% баллами')
        late = {p['tier']: p for p in privileges if p['group'] == 'late-checkout'}
        self.assertEqual(sorted(late), ['ambassador', 'gold', 'platinum', 'silver', 'titanium'])
        self.assertEqual(late['ambassador']['title'], 'Поздний выезд до 18:00')
        self.assertTrue(late['silver']['footnote'].startswith('Не гарантированно'))
        tiers = {t['id']: t for t in program['tiers']}
        self.assertEqual((tiers['platinum']['cashbackBonus'], tiers['platinum']['cashbackRate']), (50.0, 0.075))
        self.assertEqual(tiers['titanium']['permanent'], {'lifetime': 200_000, 'years': 4})
        self.assertIsNone(tiers['bronze']['permanent'])


class TierSettingsAdminTests(BaseAPITestCase):
    def test_admin_api_edits_bonus_and_permanent(self):
        owner = self.staff_client(self.make_staff('owner'))
        r = owner.patch('/api/v1/admin/tiers/gold', {'cashbackBonus': 30, 'permanentLifetime': 120_000,
                                                     'permanentYears': 3}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['cashbackBonus'], r.json()['permanentLifetime'], r.json()['permanentYears']),
                         (30.0, 120_000, 3))
        program = self.api.get('/api/v1/loyalty/program').json()
        gold = next(t for t in program['tiers'] if t['id'] == 'gold')
        self.assertEqual((gold['cashbackRate'], gold['permanent']), (0.065, {'lifetime': 120_000, 'years': 3}))
        r = owner.patch('/api/v1/admin/privileges/late-checkout-silver', {'footnote': {'ru': 'Если есть номера'}},
                        format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_gold_member_gets_bonus_in_quote(self):
        from apps.loyalty.models import Wallet
        m = self.make_member(points=0)
        Wallet.objects.filter(member=m).update(tier='gold')
        self.auth(m)
        d = self.api.post('/api/v1/cashback-requests/quote', {'itemId': 'spa-stone', 'quantity': 1}, format='json').json()
        self.assertEqual((d['rate'], d['cashback']), (0.0625, 219))   # 3 500 × 5 % × 1,25 = 218,75 → 219
        self.assertEqual(d['bonuses'][-1], {'kind': 'tier', 'tierId': 'gold', 'percent': 25.0})
