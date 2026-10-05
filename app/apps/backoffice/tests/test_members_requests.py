"""Клиенты (корректировки, блокировка, удаление/восстановление) и заявки (эскалация)."""
from apps.cashback.models import CashbackRequest
from apps.cashback.services import create_request
from apps.common.models import AuditLog
from apps.common.tokens import issue_access
from apps.loyalty.models import Operation, OperationKind
from apps.loyalty.services import get_wallet
from apps.members.models import Member, MemberStatus
from apps.members.services import deactivate

from .base import AdminTestCase


class AdjustmentTests(AdminTestCase):
    def test_adjustment_writes_ledger_and_audit(self):
        url = f'/members/{self.member.pk}/adjustments'
        r = self.post(self.manager, url, {'points': 500, 'comment': 'Компенсация за ожидание'})
        self.assertStatus(r, 201)
        self.assertEqual(r.data['wallet']['balance'], 500)
        op = Operation.objects.get(member=self.member)
        self.assertEqual((op.kind, op.points, op.author_id, op.reason),
                         (OperationKind.ADJUSTMENT, 500, self.manager.pk, 'Компенсация за ожидание'))
        self.assertEqual(r.data['operation']['id'], op.pk)
        entry = AuditLog.objects.get(action='member.adjust')
        self.assertEqual((entry.actor_id, entry.object_id), (self.manager.pk, str(self.member.pk)))
        self.assertEqual(entry.before, {'balance': 0})
        self.assertEqual(entry.after['balance'], 500)
        self.assertEqual(entry.comment, 'Компенсация за ожидание')

        r = self.post(self.manager, url, {'points': -200, 'comment': 'Ошибка начисления'})
        self.assertStatus(r, 201)
        self.assertEqual(get_wallet(self.member).balance, 300)

    def test_adjustment_validation(self):
        url = f'/members/{self.member.pk}/adjustments'
        self.assertError(self.post(self.manager, url, {'points': 100}), 400, 'validation_error')
        self.assertError(self.post(self.manager, url, {'points': 0, 'comment': 'x'}), 400, 'validation_error')
        self.assertError(self.post(self.manager, url, {'points': -1, 'comment': 'x'}), 422, 'insufficient_points')
        self.assertFalse(Operation.objects.exists())


class MemberActionsTests(AdminTestCase):
    def test_search_and_filters(self):
        r = self.get(self.manager, '/members', q='Айбек')
        self.assertEqual([m['id'] for m in r.data['items']], [self.member.pk])
        r = self.get(self.manager, '/members', q=self.member.member_id)
        self.assertEqual(len(r.data['items']), 1)
        r = self.get(self.manager, '/members', q='700000001')
        self.assertEqual(len(r.data['items']), 1)
        r = self.get(self.manager, '/members', tier='gold')
        self.assertEqual(r.data['items'], [])

    def test_block_unblock(self):
        r = self.post(self.manager, f'/members/{self.member.pk}/block', {'reason': 'Мошенничество'})
        self.assertStatus(r, 200)
        self.assertEqual(r.data['status'], MemberStatus.BLOCKED)
        self.assertStatus(self.post(self.manager, f'/members/{self.member.pk}/block', {'reason': 'x'}), 409)
        r = self.post(self.manager, f'/members/{self.member.pk}/unblock')
        self.assertEqual(r.data['status'], MemberStatus.ACTIVE)

    def test_birthday_and_phone(self):
        r = self.patch(self.manager, f'/members/{self.member.pk}/birthday', {'birthday': '1991-02-03'})
        self.assertStatus(r, 200)
        self.assertEqual(r.data['profile']['birthday'], '1991-02-03')
        Member.objects.create(phone='+996700000002', first_name='B', last_name='B')
        r = self.patch(self.manager, f'/members/{self.member.pk}/phone', {'phone': '+996 700 000 002'})
        self.assertError(r, 409, 'phone_taken')
        r = self.patch(self.manager, f'/members/{self.member.pk}/phone', {'phone': '+996 700 000 009'})
        self.assertStatus(r, 200)
        self.assertEqual(r.data['profile']['phone'], '+996700000009')
        self.assertTrue(AuditLog.objects.filter(action='member.phone').exists())

    def test_deleted_marker_restore_and_purge(self):
        deactivate(self.member)
        r = self.get(self.manager, f'/members/{self.member.pk}')
        self.assertTrue(r.data['deletion']['note'].startswith('удалён, будет стёрт '))
        r = self.post(self.manager, f'/members/{self.member.pk}/restore')
        self.assertStatus(r, 200)
        self.assertEqual(r.data['status'], MemberStatus.ACTIVE)
        self.assertStatus(self.post(self.staff, f'/members/{self.member.pk}/purge-now', {'comment': 'x'}), 403)
        self.assertStatus(self.post(self.manager, f'/members/{self.member.pk}/purge-now'), 400)
        r = self.post(self.manager, f'/members/{self.member.pk}/purge-now', {'comment': 'Обращение О-000001'})
        self.assertStatus(r, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, MemberStatus.PURGED)
        self.assertIsNone(self.member.phone)

    def test_export(self):
        self.post(self.manager, f'/members/{self.member.pk}/adjustments', {'points': 5, 'comment': 'x'})
        r = self.get(self.manager, f'/members/{self.member.pk}/export')
        self.assertStatus(r, 200)
        self.assertEqual(r.data['profile']['phone'], '+996700000001')
        self.assertEqual(len(r.data['operations']), 1)
        self.assertTrue(AuditLog.objects.filter(action='member.export').exists())


class EscalationTests(AdminTestCase):
    def setUp(self):
        self.req, _ = create_request(self.member, {'itemId': 'massage', 'quantity': 1, 'method': 'cash'})

    def staff_adjust(self, total):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + issue_access('staff', self.staff.pk))
        return self.client.post(f'/api/v1/staff/requests/{self.req.pk}/adjust',
                                {'total': total, 'reason': 'Чек на другую сумму'}, format='json')

    def test_escalated_adjustment_is_approved_by_manager(self):
        r = self.staff_adjust(3000)  # +200 % > порога
        self.assertStatus(r, 202)
        self.req.refresh_from_db()
        self.assertTrue(self.req.escalated)
        self.assertEqual((self.req.proposed_total, self.req.total), (3000, 1000))

        # сотрудник не может одобрить эскалацию
        self.assertStatus(self.post(self.staff, f'/cashback-requests/{self.req.pk}/approve-escalation'), 403)
        r = self.get(self.manager, '/cashback-requests', escalated='1')
        self.assertEqual([x['id'] for x in r.data['items']], [self.req.pk])

        r = self.post(self.manager, f'/cashback-requests/{self.req.pk}/approve-escalation',
                      {'confirm': True, 'cashReceived': True})
        self.assertStatus(r, 200)
        self.req.refresh_from_db()
        self.assertEqual((self.req.total, self.req.original_total, self.req.status), (3000, 1000, 'confirmed'))
        self.assertFalse(self.req.escalated)
        self.assertEqual(self.req.adjusted_by_id, self.manager.pk)
        self.assertTrue(AuditLog.objects.filter(action='request.approve_escalation', actor=self.manager).exists())

    def test_cashback_limit_escalation_confirms(self):
        CashbackRequest.objects.filter(pk=self.req.pk).update(escalated=True, escalation_reason='cashback_limit',
                                                              proposed_by=self.staff, cash_received=True)
        r = self.post(self.owner, f'/cashback-requests/{self.req.pk}/approve-escalation')
        self.assertStatus(r, 200)
        self.assertEqual(r.data['status'], 'confirmed')
        self.assertEqual(r.data['confirmedBy'], self.owner.pk)

    def test_not_escalated_and_decline(self):
        r = self.post(self.manager, f'/cashback-requests/{self.req.pk}/approve-escalation')
        self.assertError(r, 409, 'invalid_status')
        self.staff_adjust(3000)
        r = self.post(self.manager, f'/cashback-requests/{self.req.pk}/decline-escalation', {'comment': 'нет'})
        self.assertStatus(r, 200)
        self.req.refresh_from_db()
        self.assertEqual((self.req.escalated, self.req.total, self.req.status), (False, 1000, 'pending'))

    def test_admin_reject_and_confirm(self):
        r = self.post(self.manager, f'/cashback-requests/{self.req.pk}/reject', {})
        self.assertError(r, 400, 'validation_error')
        r = self.post(self.manager, f'/cashback-requests/{self.req.pk}/reject', {'reason': 'Не пришёл'})
        self.assertStatus(r, 200)
        self.assertEqual(r.data['status'], 'rejected')
        r = self.post(self.manager, f'/cashback-requests/{self.req.pk}/confirm', {'cashReceived': True})
        self.assertError(r, 409, 'invalid_status')
