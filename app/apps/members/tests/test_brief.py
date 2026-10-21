from django.test import TestCase

from apps.common.mdlite import render


class ContentBriefTests(TestCase):
    def test_page(self):
        r = self.client.get('/brief/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ТЗ на контент для приложения')
        self.assertContains(r, '<table>')
        self.assertContains(r, 'type="checkbox"')

    def test_mdlite(self):
        title, html = render('# Т\n\n## Раздел\n\nТекст **жирный** <b>\n\n- [ ] пункт\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n')
        self.assertEqual(title, 'Т')
        self.assertIn('<h2>Раздел</h2>', html)
        self.assertIn('<strong>жирный</strong> &lt;b&gt;', html)
        self.assertIn('<td>1</td><td>2</td>', html)
