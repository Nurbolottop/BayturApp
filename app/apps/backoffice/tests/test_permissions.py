"""Две роли: директор (всё) и администратор кассы (заявки, оплата баллами, клиенты и обращения своих точек)."""
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


class DirectorTests(AdminTestCase):
    """Директор — полный доступ (бывшие менеджер, редактор, бухгалтер, служба заботы — тоже директоры)."""

    def test_director_edits_prices_rules_and_promos(self):
        self.assertStatus(self.patch(self.owner, '/items/massage', {'price': 1200}), 200)
        r = self.patch(self.owner, '/categories/spa', {'rules': {'rate': 0.07, 'methods': ['cash']}})
        self.assertStatus(r, 200)
        r = self.post(self.owner, '/items/massage/promos', {'rate': 0.1, 'tag': {'ru': '×2'},
                                                            'startsAt': '2026-09-01', 'endsAt': '2026-09-30'})
        self.assertStatus(r, 201)

    def test_only_two_roles(self):
        r = self.get(self.owner, '/staff/roles')
        self.assertEqual([x['id'] for x in r.data['items']], ['owner', 'staff'])
        self.assertEqual([x['label'] for x in r.data['items']], ['Директор', 'Администратор кассы'])


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
        r = self.post(self.owner, '/staff', {'email': 'New@Baytur.kg', 'fullName': 'Новый', 'role': 'owner'})
        self.assertStatus(r, 201)
        self.assertTrue(r.data['temporaryPassword'])
        self.assertEqual(r.data['email'], 'new@baytur.kg')
        # администратор кассы: телефон + PIN + точка, без email и пароля
        r = self.post(self.owner, '/staff', {'fullName': 'Касса бассейна', 'role': 'staff', 'phone': '+996 555 12 34 56',
                                             'outletIds': ['reception'], 'pin': '123456'})
        self.assertError(r, 400, 'pin_weak')
        r = self.post(self.owner, '/staff', {'fullName': 'Касса бассейна', 'role': 'staff', 'phone': '+996555123456',
                                             'outletIds': ['reception'], 'pin': '480215'})
        self.assertStatus(r, 201)
        self.assertEqual((r.data['phone'], r.data['email'], r.data['pinSet']), ('+996555123456', None, True))
        self.assertNotIn('temporaryPassword', r.data)
        self.assertError(self.post(self.owner, '/staff', {'fullName': 'Без точки', 'role': 'staff',
                                                          'phone': '+996555123457', 'pin': '480215'}), 400,
                         'validation_error')
        self.assertStatus(self.post(self.owner, f'/staff/{r.data["id"]}/set-pin', {'pin': '731905'}), 200)
        r = self.post(self.owner, f'/staff/{self.staff.pk}/reset-2fa')
        self.assertStatus(r, 200)
        self.assertFalse(r.data['totpEnabled'])
        self.assertStatus(self.post(self.owner, f'/staff/{self.owner.pk}/deactivate'), 400)


class CashierAppLoginTests(AdminTestCase):
    """Приложение кассира: вход по телефону и PIN, блокировка после 5 ошибок, директор — только веб."""

    def setUp(self):
        super().setUp()
        self.staff.phone = '+996700111222'
        self.staff.email = None              # как в жизни: у администратора кассы нет email и пароля
        self.staff.set_unusable_password()
        self.staff.set_pin('480215')
        self.staff.save()
        self.client.credentials()

    def login(self, phone='+996 700 111 222', pin='480215'):
        return self.client.post('/api/v1/staff/auth/login', {'phone': phone, 'pin': pin}, format='json')

    def test_login_and_work_with_own_outlet(self):
        r = self.login()
        self.assertStatus(r, 200)
        self.assertEqual((r.data['profile']['role'], r.data['profile']['outlets']), ('staff', ['reception']))
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + r.data['accessToken'])
        self.assertStatus(self.client.get('/api/v1/staff/me'), 200)
        self.assertStatus(self.client.get('/api/v1/staff/queue'), 200)
        self.assertStatus(self.client.get('/api/v1/admin/items'), 403)      # каталог — только директор
        r = self.client.post('/api/v1/staff/auth/refresh', {'refreshToken': r.data['refreshToken']}, format='json')
        self.assertStatus(r, 200)

    def test_wrong_pin_locks_after_five(self):
        for _ in range(5):
            self.assertError(self.login(pin='000001'), 401, 'invalid_credentials')
        self.assertError(self.login(), 429, 'rate_limited')               # даже верный PIN — подождать
        self.staff.refresh_from_db()
        self.assertIsNotNone(self.staff.pin_locked_until)

    def test_unknown_phone_and_director_cannot_use_pin(self):
        self.assertError(self.login(phone='+996700999999'), 401, 'invalid_credentials')
        self.owner.phone = '+996700333444'
        self.owner.set_pin('480215')
        self.owner.save()
        self.assertError(self.login(phone='+996700333444'), 401, 'invalid_credentials')

    def test_change_pin(self):
        token = self.login().data['accessToken']
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        r = self.client.post('/api/v1/staff/me/pin', {'currentPin': '480215', 'newPin': '111111'}, format='json')
        self.assertError(r, 400, 'pin_weak')
        r = self.client.post('/api/v1/staff/me/pin', {'currentPin': '480215', 'newPin': '730519'}, format='json')
        self.assertStatus(r, 200)
        self.client.credentials()
        self.assertStatus(self.login(pin='730519'), 200)

    def test_administrator_cannot_sign_in_to_web(self):
        self.staff.email = 'cashier@baytur.kg'
        self.staff.set_password('Passw0rd!x-long')
        self.staff.save()
        r = self.client.post('/api/v1/admin/auth/login', {'email': self.staff.email, 'password': 'Passw0rd!x-long'},
                             format='json')
        self.assertError(r, 403, 'staff_use_app')
