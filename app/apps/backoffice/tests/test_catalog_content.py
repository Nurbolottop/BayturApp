"""Каталог (защита от удаления), публикация контента (переводы), уровни (пороги)."""
from apps.cashback.services import create_request
from apps.catalog.models import Item
from apps.common.i18n import l10n
from apps.common.models import AuditLog
from apps.content.models import Article, Story
from apps.loyalty.models import Wallet

from .base import AdminTestCase

FULL = {'ru': 'Текст', 'ky': 'Текст', 'en': 'Text'}


class ItemDeleteTests(AdminTestCase):
    def test_item_with_requests_can_only_be_hidden(self):
        create_request(self.member, {'itemId': 'massage', 'quantity': 1, 'method': 'cash'})
        r = self.delete(self.manager, '/items/massage')
        self.assertError(r, 409, 'item_in_use')
        self.assertTrue(Item.objects.filter(pk='massage').exists())
        r = self.post(self.manager, '/items/massage/hide')
        self.assertStatus(r, 200)
        self.assertFalse(r.data['isActive'])
        self.assertTrue(AuditLog.objects.filter(action='item.hide', object_id='massage').exists())

    def test_item_without_requests_is_deleted(self):
        r = self.post(self.manager, '/items', {'id': 'yoga', 'category': 'spa', 'outlet': 'spa', 'title': FULL,
                                               'price': 500, 'pricing': {'type': 'unit', 'unit': 'session'},
                                               'features': [{'icon': 'time', 'text': {'ru': '60 мин'}}]})
        self.assertStatus(r, 201)
        self.assertEqual(r.data['features'], [{'icon': 'time', 'text': {'ru': '60 мин', 'ky': '', 'en': ''}}])
        self.assertStatus(self.post(self.manager, '/items', {'id': 'yoga', 'category': 'spa', 'title': FULL,
                                                             'price': 1, 'pricing': {'type': 'check'}}), 400)
        self.assertStatus(self.delete(self.manager, '/items/yoga'), 204)
        self.assertFalse(Item.objects.filter(pk='yoga').exists())
        self.assertTrue(AuditLog.objects.filter(action='item.delete', object_id='yoga').exists())

    def test_sort(self):
        Item.objects.create(id='sauna', category=self.category, title=FULL, price=1, pricing={'type': 'check'})
        r = self.post(self.manager, '/items/sort', {'ids': ['sauna', 'massage']})
        self.assertStatus(r, 200)
        self.assertLess(Item.objects.get(pk='sauna').sort_order, Item.objects.get(pk='massage').sort_order)


class PublishTests(AdminTestCase):
    def test_publish_requires_translations(self):
        r = self.post(self.editor, '/articles', {'id': 'news', 'title': {'ru': 'Новости'}, 'lead': {'ru': 'Коротко'},
                                                 'body': {'ru': ['Абзац']}})
        self.assertStatus(r, 201)
        r = self.post(self.editor, '/articles/news/publish')
        self.assertError(r, 422, 'translations_missing')
        self.assertEqual(r.data['error']['missing']['title'], ['ky', 'en'])
        self.assertEqual(Article.objects.get(pk='news').status, 'draft')

        # явное «использовать ru»
        self.patch(self.editor, '/articles/news', {'useRuFallback': True})
        r = self.post(self.editor, '/articles/news/publish')
        self.assertStatus(r, 200)
        self.assertEqual(r.data['status'], 'published')
        self.assertTrue(AuditLog.objects.filter(action='article.publish', object_id='news').exists())

        # опубликованное нельзя «сломать» правкой без fallback
        r = self.patch(self.editor, '/articles/news', {'useRuFallback': False})
        self.assertError(r, 422, 'translations_missing')
        self.assertStatus(self.post(self.editor, '/articles/news/unpublish'), 200)

    def test_publish_with_all_translations(self):
        self.post(self.editor, '/articles', {'id': 'full', 'title': FULL, 'body': {'ru': ['a'], 'ky': ['b'], 'en': ['c']}})
        r = self.post(self.editor, '/articles/full/publish')
        self.assertStatus(r, 200)
        r = self.get(self.editor, '/articles/full/preview', lang='en')
        self.assertEqual(r.data['data']['title'], 'Text')

    def test_story_slides_bump_updated_at_and_are_checked(self):
        r = self.post(self.editor, '/stories', {'category': 'spa', 'title': FULL,
                                                'slides': [{'title': FULL, 'itemId': 'massage'}]})
        self.assertStatus(r, 201)
        sid = r.data['id']
        self.assertEqual(len(r.data['slides']), 1)
        before = Story.objects.get(pk=sid).updated_at
        r = self.put(self.editor, f'/stories/{sid}/slides', [{'title': {'ru': 'Только ru'}}, {'title': FULL}])
        self.assertStatus(r, 200)
        self.assertEqual(len(r.data['slides']), 2)
        self.assertGreater(Story.objects.get(pk=sid).updated_at, before)
        r = self.post(self.editor, f'/stories/{sid}/publish')
        self.assertError(r, 422, 'translations_missing')
        self.assertIn('slides[0].title', r.data['error']['missing'])

    def test_promo_needs_article(self):
        Article.objects.create(id='a1', title=l10n('A', 'A', 'A'))
        r = self.post(self.editor, '/promos', {'articleId': 'a1', 'subtitle': FULL, 'cta': FULL,
                                               'activeFrom': '2026-10-01', 'activeTo': '2026-09-01'})
        self.assertStatus(r, 400)
        r = self.post(self.editor, '/promos', {'articleId': 'a1', 'subtitle': FULL, 'cta': FULL})
        self.assertStatus(r, 201)
        self.assertStatus(self.post(self.editor, f'/promos/{r.data["id"]}/publish'), 200)
        self.assertError(self.delete(self.editor, '/articles/a1'), 409, 'in_use')


class TierTests(AdminTestCase):
    def thresholds(self, **changes):
        return {'tiers': [{'id': k, 'from': v} for k, v in changes.items()]}

    def test_thresholds_must_start_at_zero_and_increase(self):
        r = self.put(self.manager, '/tiers', self.thresholds(bronze=10))
        self.assertError(r, 422, 'tiers_invalid')
        r = self.put(self.manager, '/tiers', self.thresholds(gold=1000))
        self.assertError(r, 422, 'tiers_invalid')
        r = self.put(self.manager, '/tiers', self.thresholds(gold=900))
        self.assertError(r, 422, 'tiers_invalid')
        r = self.post(self.manager, '/tiers/preview', {'thresholds': {'silver': 20000}})
        self.assertError(r, 422, 'tiers_invalid')
        r = self.put(self.manager, '/tiers', self.thresholds(unknown=1))
        self.assertError(r, 400, 'validation_error')

    def test_preview_and_recalc(self):
        Wallet.objects.filter(member=self.member).update(lifetime=800, tier_id='bronze')
        r = self.post(self.manager, '/tiers/preview', {'thresholds': {'silver': 500}})
        self.assertStatus(r, 200)
        self.assertEqual(r.data['total'], 1)
        self.assertEqual(Wallet.objects.get(member=self.member).tier_id, 'bronze')  # превью не сохраняет

        r = self.put(self.manager, '/tiers', self.thresholds(silver=500))
        self.assertStatus(r, 200)
        self.assertEqual(r.data['upgraded'], 1)
        self.assertEqual([t['from'] for t in r.data['items']], [0, 500, 5000, 20000, 50000])
        self.assertEqual(Wallet.objects.get(member=self.member).tier_id, 'silver')
        self.assertTrue(AuditLog.objects.filter(action='tiers.update').exists())

    def test_privilege_texts_for_editor(self):
        r = self.post(self.manager, '/privileges', {'id': 'parking', 'tier': 'silver', 'icon': 'parking',
                                                    'title': FULL, 'short': FULL, 'description': FULL})
        self.assertStatus(r, 201)
        self.assertStatus(self.patch(self.editor, '/privileges/parking', {'short': FULL}), 200)
        self.assertStatus(self.patch(self.editor, '/privileges/parking', {'tier': 'gold'}), 403)
        self.assertStatus(self.post(self.manager, '/privileges', {'id': 'x', 'tier': 'silver', 'icon': 'rocket',
                                                                  'title': FULL, 'short': FULL,
                                                                  'description': FULL}), 400)
