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
        self.assertContains(r, '100 баллов = 1 сом')
        self.assertContains(r, '<h2>Уровни</h2>', html=True)
        self.assertEqual(self.client.get('/legal/deletion').status_code, 404)

    def test_text_is_escaped(self):
        from apps.members.web import render_legal_text
        title, html = render_legal_text('Заголовок\n\n<script>x</script>\n- пункт', {})
        self.assertEqual(title, 'Заголовок')
        self.assertNotIn('<script>', html)
        self.assertIn('<li>пункт</li>', html)


class NewPrivilegesTests(BaseAPITestCase):
    def test_26_privileges_with_known_icons(self):
        privileges = self.api.get('/api/v1/loyalty/program').json()['privileges']
        self.assertEqual(len(privileges), 26)
        self.assertTrue(all(p['icon'] in PERK_ICONS for p in privileges))
        by_id = {p['id']: p for p in privileges}
        self.assertEqual((by_id['night-pool']['tier'], by_id['night-pool']['icon']), ('platinum', 'pool'))
        self.assertEqual(by_id['photo']['tier'], 'titanium')
