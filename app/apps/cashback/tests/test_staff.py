from apps.cashback import services
from apps.cashback.models import RequestStatus
from apps.common.models import AuditLog
from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Operation

S = '/api/v1/staff'


class StaffDeskTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=500_000)
        self.spa_staff = self.make_staff('staff', outlets=['spa'])
        self.waiter = self.make_staff('staff', outlets=['davinci'])
        self.spa = self.staff_client(self.spa_staff)
        self.req, _ = services.create_request(self.member, {'itemId': 'spa-stone', 'quantity': 2, 'method': 'cash'})

    def test_queue_only_own_outlet(self):
        food, _ = services.create_request(self.member, {'itemId': 'food-davinci', 'checkAmount': 4000,
                                                        'method': 'cash'})
        ids = [i['id'] for i in self.spa.get(f'{S}/queue').json()['items']]
        self.assertEqual(ids, [self.req.pk])
        waiter = self.staff_client(self.waiter)
        self.assertEqual(waiter.get(f'{S}/requests/{self.req.pk}').status_code, 404)
        self.assertEqual(waiter.post(f'{S}/requests/{self.req.pk}/confirm', {'cashReceived': True},
                                     format='json').status_code, 404)
        card = waiter.get(f'{S}/requests/{food.pk}').json()
        self.assertNotIn('balance', card['member'])
        self.assertIn('•', card['member']['phone'])

    def test_client_cannot_use_staff_api(self):
        self.auth(self.member)
        self.assertEqual(self.api.get(f'{S}/queue').status_code, 401)

    def test_cash_confirm_requires_checkbox_and_is_audited(self):
        r = self.spa.post(f'{S}/requests/{self.req.pk}/confirm', {}, format='json')
        self.assertEqual(r.json()['error']['code'], 'cash_not_received')
        r = self.spa.post(f'{S}/requests/{self.req.pk}/confirm', {'cashReceived': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'confirmed')
        self.assertEqual(r.json()['confirmedBy'], self.spa_staff.pk)
        self.assertTrue(AuditLog.objects.filter(action='request.confirm', actor=self.spa_staff).exists())
        # второй сотрудник → 409 с актуальным статусом
        other = self.staff_client(self.make_staff('staff', outlets=['spa']))
        r = other.post(f'{S}/requests/{self.req.pk}/confirm', {'cashReceived': True}, format='json')
        self.assertEqual((r.status_code, r.json()['error']['status']), (409, 'confirmed'))

    def test_own_account_forbidden(self):
        self.spa_staff.phone = self.member.phone
        self.spa_staff.save()
        r = self.spa.post(f'{S}/requests/{self.req.pk}/confirm', {'cashReceived': True}, format='json')
        self.assertEqual(r.json()['error']['code'], 'own_account')

    def test_adjust_preview_small_adjust_and_escalation(self):
        p = self.spa.post(f'{S}/requests/{self.req.pk}/adjust/preview', {'total': 6500}, format='json').json()
        self.assertEqual((p['total'], p['cashback'], p['needsManager']), (6500, 6500 * 7, False))
        r = self.spa.post(f'{S}/requests/{self.req.pk}/adjust', {'total': 6500}, format='json')
        self.assertEqual(r.json()['error']['code'], 'validation_error')  # причина обязательна
        r = self.spa.post(f'{S}/requests/{self.req.pk}/adjust', {'total': 6500, 'reason': 'чек'}, format='json')
        self.assertEqual((r.status_code, r.json()['originalTotal'], r.json()['split']['total']), (200, 7000, 6500))
        # > 20 % от исходной суммы → менеджеру
        r = self.spa.post(f'{S}/requests/{self.req.pk}/adjust', {'total': 3000, 'reason': 'чек'}, format='json')
        self.assertEqual(r.status_code, 202)
        self.assertTrue(r.json()['escalated'])
        self.assertEqual(r.json()['split']['total'], 6500)  # сумма не изменилась до решения менеджера
        r = self.spa.post(f'{S}/requests/{self.req.pk}/confirm', {'cashReceived': True}, format='json')
        self.assertEqual(r.json()['error']['code'], 'needs_manager')

    def test_cashback_limit_escalation(self):
        self.settings_obj(staff_cashback_limit_points=10_000)
        r = self.spa.post(f'{S}/requests/{self.req.pk}/confirm', {'cashReceived': True}, format='json')
        self.assertEqual(r.status_code, 202)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, RequestStatus.PENDING)
        # менеджер (не привязан к точкам) подтверждает сам
        manager = self.staff_client(self.make_staff('owner'))
        r = manager.post(f'{S}/requests/{self.req.pk}/confirm', {'cashReceived': True}, format='json')
        self.assertEqual(r.json()['status'], 'confirmed')

    def test_reject_reason(self):
        r = self.spa.post(f'{S}/requests/{self.req.pk}/reject', {'reasonCode': 'other'}, format='json')
        self.assertEqual(r.json()['error']['code'], 'validation_error')
        r = self.spa.post(f'{S}/requests/{self.req.pk}/reject', {'reasonCode': 'duplicate'}, format='json')
        self.assertEqual(r.json()['status'], 'rejected')
        self.assertEqual(self.wallet(self.member).reserved, 0)

    def test_staff_never_touches_points_directly(self):
        before = Operation.objects.count()
        for url in ('/api/v1/admin/members/1/adjustments',):
            self.assertIn(self.spa.post(url, {'points': 100, 'comment': 'x'}, format='json').status_code, (403, 404))
        self.assertEqual(Operation.objects.count(), before)

    def test_member_search_and_qr_scan(self):
        r = self.spa.get(f'{S}/members', {'q': self.member.member_id}).json()
        self.assertEqual(r['items'][0]['memberId'], self.member.member_id)
        self.assertNotIn('balance', r['items'][0])
        r = self.spa.get(f'{S}/members', {'q': self.member.phone[-9:]}).json()
        self.assertEqual(len(r['items']), 1)
        self.auth(self.member)
        token = self.api.get('/api/v1/me/member-qr').json()['token']
        r = self.spa.post(f'{S}/scan', {'token': token}, format='json')
        self.assertEqual(r.json()['memberId'], self.member.member_id)
        self.assertEqual(self.spa.post(f'{S}/scan', {'token': token + 'x'}, format='json').json()['error']['code'],
                         'qr_invalid')

    def test_shift_summary(self):
        self.spa.post(f'{S}/requests/{self.req.pk}/confirm', {'cashReceived': True}, format='json')
        d = self.spa.get(f'{S}/shift').json()
        self.assertEqual(len(d['confirmed']), 1)
        self.assertEqual(d['cashTotal'], 7000)
