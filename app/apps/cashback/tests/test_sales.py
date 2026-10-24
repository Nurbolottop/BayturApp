from datetime import timedelta

from django.utils import timezone

from apps.cashback.models import CashbackRequest
from apps.catalog.models import Outlet
from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Operation

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

    def sell(self, method, item='spa-stone', key=None, desk=None, token=None, **data):
        headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
        with self.captureOnCommitCallbacks(execute=True):
            return (desk or self.desk).post(f'{S}/sales', {'payToken': token or self.pay_token, 'itemId': item,
                                                           'method': method, 'quantity': 1, **data},
                                            format='json', **headers)

    def test_quote(self):
        q = self.desk.post(f'{S}/sales/quote', {'payToken': self.pay_token, 'itemId': 'spa-stone', 'quantity': 2},
                           format='json').json()
        self.assertEqual((q['total'], q['quantity'], q['points'], q['enough'], q['shortSom']),
                         (7000, 2, 70_000, False, 2000))
        self.assertGreater(q['cashback'], 0)
        self.assertEqual((q['needsManager'], q['duplicate']), (False, None))
        self.assertNotIn('available', q)

    def test_cash_and_card_confirmed_at_once(self):
        r = self.sell('cash')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual((d['status'], d['method'], d['createdBy']), ('confirmed', 'cash', self.cashier.pk))
        self.assertIsNotNone(d['cancelUntil'])
        r = self.sell('card', key='k-card')
        self.assertEqual((r.json()['status'], r.json()['method']), ('confirmed', 'card'))
        self.assertIsNotNone(r.json()['duplicateOf'])            # та же услуга за 10 минут — повтор
        shift = self.desk.get(f'{S}/shift').json()
        self.assertEqual((shift['cashTotal'], shift['cardTotal'], len(shift['confirmed'])), (3500, 3500, 2))

    def test_idempotency(self):
        a = self.sell('cash', key='same')
        b = self.sell('cash', key='same')
        self.assertEqual(a.json()['id'], b.json()['id'])
        self.assertEqual(CashbackRequest.objects.count(), 1)

    def test_points_client_approves(self):
        r = self.sell('points')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(d['status'], 'awaiting_client')
        self.assertIsNotNone(d['confirmUntil'])
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
        req = CashbackRequest.objects.get(pk=d['id'])
        self.assertEqual(req.confirmed_by_id, self.cashier.pk)

    def test_points_decline_and_timeout(self):
        rid = self.sell('points').json()['id']
        self.auth(self.member)
        r = self.api.post(f'/api/v1/cashback-requests/{rid}/decline')
        self.assertEqual(r.json()['status'], 'rejected')
        self.assertEqual(self.wallet(self.member).reserved, 0)
        r = self.api.post(f'/api/v1/cashback-requests/{rid}/approve')
        self.assertEqual((r.status_code, r.json()['error']['code']), (409, 'invalid_status'))

        rid = self.sell('points', key='second').json()['id']
        CashbackRequest.objects.filter(pk=rid).update(confirm_until=timezone.now() - timedelta(seconds=1))
        from apps.cashback.services import process_due
        process_due()
        req = CashbackRequest.objects.get(pk=rid)
        self.assertEqual((req.status, req.reject_code), ('rejected', 'client_timeout'))
        self.assertEqual(self.wallet(self.member).reserved, 0)

    def test_points_not_enough(self):
        r = self.sell('points', quantity=2)
        self.assertEqual((r.status_code, r.json()['error']['code'], r.json()['error'].get('shortSom')),
                         (422, 'insufficient_points', 2000))

    def test_qr_payment(self):
        from apps.payments.services import set_status
        r = self.sell('qr')
        d = r.json()
        self.assertEqual((r.status_code, d['status']), (201, 'awaiting_payment'), r.content)
        self.assertTrue(d['payQr'])
        req = CashbackRequest.objects.select_related('payment').get(pk=d['id'])
        with self.captureOnCommitCallbacks(execute=True):
            set_status(req.payment.pk, 'paid', req.payment.amount)
        d = self.desk.get(f'{S}/requests/{req.pk}').json()
        self.assertEqual((d['status'], d['paidOnline'], d['payQr']), ('confirmed', True, None))

    def test_receipt_outlet_and_check_items(self):
        Outlet.objects.filter(pk='davinci').update(receipt_required=True)
        items = {i['id']: i for i in self.desk.get(f'{S}/points/items').json()['items']}
        self.assertTrue(items['food-davinci']['receiptRequired'])
        self.assertFalse(items['spa-stone']['receiptRequired'])
        r = self.sell('cash', item='food-davinci', quantity=None, checkAmount=1000)
        self.assertEqual((r.status_code, r.json()['error']['code']), (422, 'method_not_allowed'))
        r = self.sell('points', item='food-davinci', quantity=None, checkAmount=1000)
        self.assertEqual(r.json()['status'], 'awaiting_client')
        Outlet.objects.filter(pk='davinci').update(receipt_required=False)
        r = self.sell('card', item='food-davinci', quantity=None, checkAmount=1000, key='card')
        self.assertEqual(r.json()['error']['code'], 'method_not_allowed')  # сумму вписал кассир — только баллы

    def test_threshold_goes_to_director(self):
        Outlet.objects.filter(pk='spa').update(manager_threshold=3000)
        q = self.desk.post(f'{S}/sales/quote', {'payToken': self.pay_token, 'itemId': 'spa-stone', 'quantity': 1},
                           format='json').json()
        self.assertTrue(q['needsManager'])
        r = self.sell('points')
        self.assertEqual((r.status_code, r.json()['status'], r.json()['escalated']), (202, 'pending', True))
        owner = self.make_staff('owner')
        from django.test import RequestFactory
        from apps.cashback import desk
        http = RequestFactory().post('/')
        http.user = owner
        with self.captureOnCommitCallbacks(execute=True):
            req = desk.approve_escalation(http, r.json()['id'])
        self.assertEqual(req.status, 'awaiting_client')              # дальше подтверждает клиент

    def test_cancel(self):
        rid = self.sell('cash').json()['id']
        other = self.staff_client(self.make_staff('staff', outlets=['spa']))
        r = other.post(f'{S}/requests/{rid}/cancel', {'reason': 'ошибка'}, format='json')
        self.assertEqual(r.status_code, 403)                          # только свою
        with self.captureOnCommitCallbacks(execute=True):
            r = self.desk.post(f'{S}/requests/{rid}/cancel', {'reason': 'не та услуга'}, format='json')
        self.assertEqual((r.status_code, r.json()['status'], r.json()['cancelReason']),
                         (200, 'cancelled', 'не та услуга'))
        shift = self.desk.get(f'{S}/shift').json()
        self.assertEqual((shift['cashTotal'], len(shift['cancelled']), len(shift['confirmed'])), (0, 1, 0))
        self.assertTrue(self.member.notifications.filter(kind='request.cancelled').exists())

        rid = self.sell('cash', key='late').json()['id']
        CashbackRequest.objects.filter(pk=rid).update(cancel_until=timezone.now() - timedelta(seconds=1))
        r = self.desk.post(f'{S}/requests/{rid}/cancel', {'reason': 'поздно'}, format='json')
        self.assertEqual((r.status_code, r.json()['error']['code']), (409, 'cancel_expired'))

    def test_cancel_returns_points_and_revokes_cashback(self):
        from apps.cashback.services import credit_request
        rid = self.sell('points').json()['id']
        self.auth(self.member)
        self.api.post(f'/api/v1/cashback-requests/{rid}/approve')
        self.assertEqual(self.wallet(self.member).balance, 15_000)
        with self.captureOnCommitCallbacks(execute=True):
            self.desk.post(f'{S}/requests/{rid}/cancel', {'reason': 'клиент передумал'}, format='json')
        self.assertEqual(self.wallet(self.member).balance, 50_000)

        rid = self.sell('cash', key='cb').json()['id']
        credit_request(rid)
        cashback = CashbackRequest.objects.get(pk=rid).cashback
        self.assertEqual(self.wallet(self.member).balance, 50_000 + cashback)
        self.desk.post(f'{S}/requests/{rid}/cancel', {'reason': 'возврат'}, format='json')
        self.assertEqual(self.wallet(self.member).balance, 50_000)
        self.assertTrue(Operation.objects.filter(request_id=rid, kind='reversal').exists())

    def test_cancel_while_waiting(self):
        rid = self.sell('points').json()['id']
        r = self.desk.post(f'{S}/requests/{rid}/cancel', {'reason': 'передумал'}, format='json')
        self.assertEqual(r.json()['status'], 'cancelled')
        self.assertEqual(self.wallet(self.member).reserved, 0)

    def test_panel_shifts_and_director_cancel(self):
        self.sell('cash')
        rid = self.sell('card', key='dup').json()['id']
        CashbackRequest.objects.filter(pk=rid).update(cancel_until=timezone.now() - timedelta(seconds=1))
        owner = self.make_staff('owner')
        self.client.force_login(owner)
        page = self.client.get('/panel/requests/shifts/')
        self.assertEqual(page.status_code, 200)
        row = page.context['rows'][0]
        self.assertEqual((row['cash'], row['card'], row['count']), (3500, 3500, 2))
        self.assertEqual(len(page.context['duplicates']), 1)
        self.assertContains(self.client.get(f'/panel/requests/{rid}/'), 'Отменить операцию')
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f'/panel/r/{rid}/cancel/', {'reason': 'ошибка кассира'})
        req = CashbackRequest.objects.get(pk=rid)
        self.assertEqual((req.status, req.cancelled_by_id, req.cancel_reason), ('cancelled', owner.pk, 'ошибка кассира'))
        page = self.client.get('/panel/requests/shifts/')
        self.assertEqual((page.context['rows'][0]['card'], len(page.context['cancelled'])), (0, 1))
        self.assertContains(self.client.get('/panel/requests/?duplicate=1'), 'повтор')
