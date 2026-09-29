"""Матрица прав §7.1: редактор / менеджер / сотрудник / бухгалтер / владелец."""
from apps.cashback.services import create_request

from .base import AdminTestCase


class AuthTests(AdminTestCase):
    def test_token_required(self):
        self.client.credentials()
        r = self.client.get('/api/v1/admin/items')
        self.assertError(r, 401, 'auth_required')

    def test_member_token_rejected(self):
        from apps.common.tokens import issue_access
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + issue_access('member', self.member.pk))
        r = self.client.get('/api/v1/admin/items')
        self.assertStatus(r, 401)


class EditorTests(AdminTestCase):
    def test_editor_edits_texts_not_prices(self):
        r = self.patch(self.editor, '/items/massage', {'title': {'ru': 'Массаж 60', 'ky': 'Массаж 60', 'en': 'Massage 60'}})
        self.assertStatus(r, 200)
        self.assertEqual(r.data['title'], {'ru': 'Массаж 60', 'ky': 'Массаж 60', 'en': 'Massage 60'})
        r = self.patch(self.editor, '/items/massage', {'price': 1})
        self.assertError(r, 403, 'permission_denied')
        self.assertEqual(r.data['error']['fields'], ['price'])
        r = self.patch(self.editor, '/categories/spa', {'rules': {'rate': 0.5}})
        self.assertError(r, 403, 'permission_denied')
        self.item.refresh_from_db()
        self.assertEqual(self.item.price, 1000)

    def test_editor_cannot_create_items_or_promos(self):
        r = self.post(self.editor, '/items', {'id': 'x', 'category': 'spa', 'title': {'ru': 'X'}, 'price': 1,
                                              'pricing': {'type': 'unit', 'unit': 'visit'}})
        self.assertStatus(r, 403)
        r = self.post(self.editor, '/items/massage/promos', {'rate': 0.1})
        self.assertStatus(r, 403)

    def test_editor_content_and_campaign_drafts_only(self):
        r = self.post(self.editor, '/articles', {'id': 'news', 'title': {'ru': 'Новости'}})
        self.assertStatus(r, 201)
        r = self.post(self.editor, '/campaigns', {'title': {'ru': 'Акция'}, 'body': {'ru': 'Текст'}})
        self.assertStatus(r, 201)
        self.assertEqual(r.data['status'], 'draft')
        r = self.post(self.editor, f'/campaigns/{r.data["id"]}/send')
        self.assertStatus(r, 403)

    def test_editor_has_no_members_payments_settings(self):
        for url in ('/members', '/payments', '/settings', '/staff', '/audit', '/complaints', '/cashback-requests'):
            self.assertStatus(self.get(self.editor, url), 403)

    def test_editor_tier_names_only(self):
        r = self.patch(self.editor, '/tiers/silver', {'name': {'ru': 'Серебро', 'ky': 'Күмүш', 'en': 'Silver'}})
        self.assertStatus(r, 200)
        r = self.patch(self.editor, '/tiers/silver', {'from': 900})
        self.assertStatus(r, 403)


class ManagerTests(AdminTestCase):
    def test_manager_edits_prices_rules_and_promos(self):
        self.assertStatus(self.patch(self.manager, '/items/massage', {'price': 1200}), 200)
        r = self.patch(self.manager, '/categories/spa', {'rules': {'rate': 0.07, 'methods': ['cash']}})
        self.assertStatus(r, 200)
        self.assertEqual(r.data['rules'], {'rate': 0.07, 'maxPointsShare': 0.5, 'methods': ['cash']})
        r = self.post(self.manager, '/items/massage/promos', {'rate': 0.1, 'tag': {'ru': '×2'},
                                                              'startsAt': '2026-09-01', 'endsAt': '2026-09-30'})
        self.assertStatus(r, 201)

    def test_manager_has_no_owner_modules(self):
        for url in ('/settings', '/staff', '/legal'):
            self.assertStatus(self.get(self.manager, url), 403)
        self.assertStatus(self.get(self.manager, '/payments'), 200)
        self.assertStatus(self.get(self.manager, '/members'), 200)

    def test_manager_cannot_refund(self):
        self.assertStatus(self.post(self.manager, '/payments/pay_x/refund', {'reason': 'x'}), 403)

    def test_audit_manager_sees_only_own(self):
        self.patch(self.manager, '/items/massage', {'price': 1100})
        self.patch(self.owner, '/items/massage', {'price': 1300})
        r = self.get(self.manager, '/audit')
        self.assertStatus(r, 200)
        self.assertTrue(r.data['items'])
        self.assertTrue(all(e['actor']['id'] == self.manager.pk for e in r.data['items']))
        r = self.get(self.owner, '/audit')
        self.assertEqual({e['actor']['id'] for e in r.data['items']}, {self.manager.pk, self.owner.pk})


class StaffRoleTests(AdminTestCase):
    def test_staff_sees_member_without_balance_and_history(self):
        r = self.get(self.staff, f'/members/{self.member.pk}')
        self.assertStatus(r, 200)
        for key in ('wallet', 'operations', 'balance', 'consents', 'devices'):
            self.assertNotIn(key, r.data)
        self.assertIn('•', r.data['phone'])
        self.assertStatus(self.get(self.staff, f'/members/{self.member.pk}/operations'), 403)
        self.assertStatus(self.post(self.staff, f'/members/{self.member.pk}/adjustments',
                                    {'points': 10, 'comment': 'x'}), 403)

    def test_staff_sees_only_own_outlet_requests(self):
        req, _ = create_request(self.member, {'itemId': 'massage', 'quantity': 1, 'method': 'cash'})
        r = self.get(self.staff, '/cashback-requests')
        self.assertEqual([x['id'] for x in r.data['items']], [req.pk])
        r = self.get(self.spa_staff, '/cashback-requests')
        self.assertEqual(r.data['items'], [])
        self.assertStatus(self.get(self.spa_staff, f'/cashback-requests/{req.pk}'), 404)

    def test_staff_has_no_catalog_or_content(self):
        for url in ('/items', '/articles', '/campaigns', '/tiers', '/payments'):
            self.assertStatus(self.get(self.staff, url), 403)
        self.assertStatus(self.get(self.staff, '/outlets'), 200)


class AccountantTests(AdminTestCase):
    def test_accountant_reads_members_and_money(self):
        r = self.get(self.accountant, f'/members/{self.member.pk}')
        self.assertStatus(r, 200)
        self.assertIn('wallet', r.data)
        self.assertStatus(self.get(self.accountant, '/payments'), 200)
        self.assertStatus(self.get(self.accountant, '/payments/reconciliation'), 200)
        self.assertStatus(self.get(self.accountant, '/cashback-requests'), 200)

    def test_accountant_cannot_change(self):
        req, _ = create_request(self.member, {'itemId': 'massage', 'quantity': 1, 'method': 'cash'})
        self.assertStatus(self.post(self.accountant, f'/cashback-requests/{req.pk}/confirm', {'cashReceived': True}),
                          403)
        self.assertStatus(self.post(self.accountant, f'/members/{self.member.pk}/adjustments',
                                    {'points': 10, 'comment': 'x'}), 403)
        self.assertStatus(self.post(self.accountant, f'/members/{self.member.pk}/block', {'reason': 'x'}), 403)
        self.assertStatus(self.patch(self.accountant, '/items/massage', {'title': {'ru': 'X'}}), 403)


class OwnerSmokeTests(AdminTestCase):
    def test_all_lists_open_for_owner(self):
        urls = ['/outlets', '/categories', '/items', '/items/massage', '/items/massage/promos', '/tiers',
                '/privileges', '/articles', '/promos', '/events', '/stories', '/members',
                f'/members/{self.member.pk}', f'/members/{self.member.pk}/requests',
                f'/members/{self.member.pk}/operations', f'/members/{self.member.pk}/export', '/cashback-requests',
                '/payments', '/payments/reconciliation', '/campaigns', '/push-templates', '/settings', '/legal',
                '/staff', '/staff/roles', '/staff/directory', '/audit', '/complaints', '/complaints/counters',
                '/complaint-categories', '/reply-templates']
        for url in urls:
            with self.subTest(url=url):
                self.assertStatus(self.get(self.owner, url), 200)

    def test_settings_update_is_audited(self):
        r = self.patch(self.owner, '/settings', {'pointsPerSom': 50, 'purgeDays': 14})
        self.assertStatus(r, 200)
        self.assertEqual((r.data['pointsPerSom'], r.data['purgeDays']), (50, 14))
        from apps.common.models import AuditLog
        e = AuditLog.objects.get(action='settings.update')
        self.assertEqual(e.before, {'points_per_som': 100, 'purge_days': 30})
        self.assertStatus(self.patch(self.owner, '/settings', {'nope': 1}), 400)

    def test_staff_create_and_reset_2fa(self):
        r = self.post(self.owner, '/staff', {'email': 'New@Baytur.kg', 'fullName': 'Новый', 'role': 'staff',
                                             'outletIds': ['reception']})
        self.assertStatus(r, 201)
        self.assertTrue(r.data['temporaryPassword'])
        self.assertEqual(r.data['email'], 'new@baytur.kg')
        self.assertEqual(r.data['outletIds'], ['reception'])
        r = self.post(self.owner, f'/staff/{self.staff.pk}/reset-2fa')
        self.assertStatus(r, 200)
        self.assertFalse(r.data['totpEnabled'])
        self.assertStatus(self.post(self.owner, f'/staff/{self.owner.pk}/deactivate'), 400)
