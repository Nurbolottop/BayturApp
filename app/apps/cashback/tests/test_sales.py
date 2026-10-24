from datetime import timedelta

from django.utils import timezone

from apps.cashback.models import CashbackRequest
from apps.catalog.models import Outlet
from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Operation

from .test_receipts import GNS_QR

S = '/api/v1/staff'


class StaffSaleTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=50_000)           # 5 000 сом (10 баллов = 1 сом)
        self.cashier = self.make_staff('staff', outlets=['spa', 'davinci'])
        self.desk = self.staff_client(self.cashier)
        self.pay_token = self.scan(self.desk)

    def scan(self, desk):
        self.auth(self.member)
        qr = self.api.get('/api/v1/me/member-qr').json()['token']
        return desk.post(f'{S}/scan', {'token': qr}, format='json').json()['payToken']

    def sell(self, item='spa-stone', key=None, desk=None, token=None, **data):
        headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
        with self.captureOnCommitCallbacks(execute=True):
            return (desk or self.desk).post(f'{S}/sales', {'payToken': token or self.pay_token, 'itemId': item,
                                                           'quantity': 1, **data}, format='json', **headers)

    def accept_cash(self, qr=GNS_QR):
        """Наличные — по QR фискального чека (Da Vinci, «по сумме чека», 2 500 сом)."""
        from apps.catalog.models import Category
        food = Category.objects.get(pk='food')
        if 'cash' not in food.methods:
            food.methods = list(food.methods) + ['cash']
            food.save()
        with self.captureOnCommitCallbacks(execute=True):
            return self.desk.post(f'{S}/cash/accept', {'payToken': self.pay_token, 'itemId': 'food-davinci',
                                                       'receiptQr': qr}, format='json')

    def test_quote(self):
        q = self.desk.post(f'{S}/sales/quote', {'payToken': self.pay_token, 'itemId': 'spa-stone', 'quantity': 2},
                           format='json').json()
        self.assertEqual((q['total'], q['quantity'], q['points'], q['enough'], q['shortSom']),
                         (7000, 2, 70_000, False, 2000))
        self.assertGreater(q['cashback'], 0)
        self.assertEqual((q['needsManager'], q['duplicate']), (False, None))
        self.assertNotIn('available', q)

    def test_points_only(self):
        r = self.sell(method='cash')
        self.assertEqual(r.status_code, 400)                          # деньги — только по чеку (/staff/cash/*)
        r = self.sell(key='k1')                                       # method не нужен — баллы
        self.assertEqual((r.status_code, r.json()['status']), (201, 'awaiting_client'), r.content)

    def test_idempotency(self):
        a = self.sell(key='same')
        b = self.sell(key='same')
        self.assertEqual(a.json()['id'], b.json()['id'])
        self.assertEqual(CashbackRequest.objects.count(), 1)

    def top_up(self, points=50_000):
        from django.db import transaction

        from apps.loyalty.models import OperationKind
        from apps.loyalty.services import lock_wallet, post_operation
        with transaction.atomic():
            post_operation(lock_wallet(self.member), OperationKind.ADJUSTMENT, points, reason='test')

    def test_duplicate(self):
        self.top_up()
        first = self.sell(key='a').json()['id']
        q = self.desk.post(f'{S}/sales/quote', {'payToken': self.pay_token, 'itemId': 'spa-stone', 'quantity': 1},
                           format='json').json()
        self.assertEqual(q['duplicate']['requestId'], first)
        self.assertEqual(self.sell(key='b').json()['duplicateOf'], first)

    def test_points_client_approves(self):
        r = self.sell()
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(d['status'], 'awaiting_client')
        self.assertIsNotNone(d['confirmUntil'])
        self.assertIsNotNone(d['cancelUntil'])
        self.assertEqual(self.wallet(self.member).balance, 50_000)   # пока не списано, только резерв
        self.assertEqual(self.wallet(self.member).reserved, 35_000)
        self.assertEqual(len(self.desk.get(f'{S}/shift').json()['confirmed']), 1)  # ожидание — в смене
        self.auth(self.member)
        with self.captureOnCommitCallbacks(execute=True):
            a = self.api.post(f'/api/v1/cashback-requests/{d["id"]}/approve', HTTP_IDEMPOTENCY_KEY='x')
        self.assertEqual((a.status_code, a.json()['status']), (200, 'confirmed'), a.content)
        again = self.api.post(f'/api/v1/cashback-requests/{d["id"]}/approve', HTTP_IDEMPOTENCY_KEY='x')
        self.assertEqual(again.status_code, 200)                     # повтор — та же заявка
        self.assertEqual(self.wallet(self.member).balance, 15_000)
        self.assertEqual(CashbackRequest.objects.get(pk=d['id']).confirmed_by_id, self.cashier.pk)

    def test_points_decline_and_timeout(self):
        rid = self.sell().json()['id']
        self.auth(self.member)
        r = self.api.post(f'/api/v1/cashback-requests/{rid}/decline')
        self.assertEqual((r.json()['status'], CashbackRequest.objects.get(pk=rid).reject_code),
                         ('rejected', 'client_declined'))
        self.assertEqual(self.wallet(self.member).reserved, 0)
        r = self.api.post(f'/api/v1/cashback-requests/{rid}/approve')
        self.assertEqual((r.status_code, r.json()['error']['code']), (409, 'invalid_status'))

        rid = self.sell(key='second').json()['id']
        CashbackRequest.objects.filter(pk=rid).update(confirm_until=timezone.now() - timedelta(seconds=1))
        from apps.cashback.services import process_due
        process_due()
        req = CashbackRequest.objects.get(pk=rid)
        self.assertEqual((req.status, req.reject_code), ('rejected', 'client_timeout'))
        self.assertEqual(self.wallet(self.member).reserved, 0)

    def test_points_not_enough(self):
        r = self.sell(quantity=2)
        self.assertEqual((r.status_code, r.json()['error']['code'], r.json()['error'].get('shortSom')),
                         (422, 'insufficient_points', 2000))

    def test_cash_receipt_is_cancellable(self):
        r = self.accept_cash()
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertIsNotNone(d['cancelUntil'])
        self.assertEqual(self.desk.get(f'{S}/shift').json()['cashTotal'], 2500)
        other = self.staff_client(self.make_staff('staff', outlets=['davinci']))
        r = other.post(f'{S}/requests/{d["id"]}/cancel', {'reason': 'ошибка'}, format='json')
        self.assertEqual(r.status_code, 403)                          # только своё
        with self.captureOnCommitCallbacks(execute=True):
            r = self.desk.post(f'{S}/requests/{d["id"]}/cancel', {'reason': 'не та услуга'}, format='json')
        self.assertEqual((r.status_code, r.json()['status'], r.json()['cancelReason']),
                         (200, 'cancelled', 'не та услуга'))
        shift = self.desk.get(f'{S}/shift').json()
        self.assertEqual((shift['cashTotal'], len(shift['cancelled']), len(shift['confirmed'])), (0, 1, 0))
        self.assertTrue(self.member.notifications.filter(kind='request.cancelled').exists())
        self.assertEqual(self.accept_cash().status_code, 201)         # чек освобождён — можно принять заново

    def test_cancel_expired(self):
        rid = self.sell().json()['id']
        CashbackRequest.objects.filter(pk=rid).update(cancel_until=timezone.now() - timedelta(seconds=1))
        r = self.desk.post(f'{S}/requests/{rid}/cancel', {'reason': 'поздно'}, format='json')
        self.assertEqual((r.status_code, r.json()['error']['code']), (409, 'cancel_expired'))

    def test_cancel_returns_points_and_revokes_cashback(self):
        from apps.cashback.services import credit_request
        rid = self.sell().json()['id']
        self.auth(self.member)
        self.api.post(f'/api/v1/cashback-requests/{rid}/approve')
        self.assertEqual(self.wallet(self.member).balance, 15_000)
        with self.captureOnCommitCallbacks(execute=True):
            self.desk.post(f'{S}/requests/{rid}/cancel', {'reason': 'клиент передумал'}, format='json')
        self.assertEqual(self.wallet(self.member).balance, 50_000)

        rid = self.accept_cash().json()['id']
        credit_request(rid)
        cashback = CashbackRequest.objects.get(pk=rid).cashback
        self.assertEqual(self.wallet(self.member).balance, 50_000 + cashback)
        self.desk.post(f'{S}/requests/{rid}/cancel', {'reason': 'возврат'}, format='json')
        self.assertEqual(self.wallet(self.member).balance, 50_000)
        self.assertTrue(Operation.objects.filter(request_id=rid, kind='reversal').exists())

    def test_cancel_while_waiting(self):
        rid = self.sell().json()['id']
        r = self.desk.post(f'{S}/requests/{rid}/cancel', {'reason': 'передумал'}, format='json')
        self.assertEqual(r.json()['status'], 'cancelled')
        self.assertEqual(self.wallet(self.member).reserved, 0)

    def test_panel_cancellations_and_duplicates(self):
        self.top_up()
        self.sell(key='a')
        rid = self.sell(key='b').json()['id']
        owner = self.make_staff('owner')
        self.client.force_login(owner)
        self.assertContains(self.client.get(f'/panel/requests/{rid}/'), 'Отменить операцию')
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f'/panel/r/{rid}/cancel/', {'reason': 'ошибка кассира'})
        req = CashbackRequest.objects.get(pk=rid)
        self.assertEqual((req.status, req.cancelled_by_id, req.cancel_reason), ('cancelled', owner.pk, 'ошибка кассира'))
        self.assertContains(self.client.get('/panel/requests/?status=cancelled'), 'ошибка кассира')
        self.assertContains(self.client.get('/panel/requests/?duplicate=1'), 'повтор')
