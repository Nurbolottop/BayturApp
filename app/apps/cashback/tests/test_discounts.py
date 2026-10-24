from django.test import Client, override_settings

from apps.cashback.models import CashbackRequest
from apps.catalog.models import Category
from apps.common.testing import BaseAPITestCase

from .test_receipts import GNS_QR

S = '/api/v1/staff'

# GNS_QR — чек на 2 500 сом (ИНН 21804199500937); spa-stone — 3 500 сом за сеанс


class CashierDiscountTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=50_000)           # 5 000 сом (10 баллов = 1 сом)
        self.cashier = self.make_staff('staff', outlets=['spa', 'davinci'])
        self.desk = self.staff_client(self.cashier)
        self.auth(self.member)
        qr = self.api.get('/api/v1/me/member-qr').json()['token']
        self.pay_token = self.desk.post(f'{S}/scan', {'token': qr}, format='json').json()['payToken']

    def sell(self, key=None, **data):
        headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
        with self.captureOnCommitCallbacks(execute=True):
            return self.desk.post(f'{S}/sales', {'payToken': self.pay_token, 'itemId': 'spa-stone', 'quantity': 1,
                                                 **data}, format='json', **headers)

    def quote(self, **data):
        return self.desk.post(f'{S}/sales/quote', {'payToken': self.pay_token, 'itemId': 'spa-stone',
                                                   'quantity': 1, **data}, format='json')

    def test_quote_with_discount(self):
        q = self.quote(amount=2000).json()
        self.assertEqual((q['total'], q['originalTotal'], q['points']), (2000, 3500, 20_000))
        q = self.quote().json()
        self.assertEqual((q['total'], q['originalTotal']), (3500, None))

    def test_amount_above_price_rejected(self):
        r = self.quote(amount=3501)
        self.assertEqual((r.status_code, r.json()['error']['code']), (422, 'amount_out_of_range'))
        self.assertEqual(r.json()['error']['max'], 3500)
        r = self.sell(amount=7001, quantity=2)
        self.assertEqual(r.status_code, 422)

    def test_sale_with_discount(self):
        r = self.sell(amount=2000, key='d1')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual((d['split']['total'], d['originalTotal'], d['status']), (2000, 3500, 'awaiting_client'))
        req = CashbackRequest.objects.get(pk=d['id'])
        self.assertEqual((req.total, req.original_total, req.points), (2000, 3500, 20_000))

    def test_full_discount_still_confirmed_by_client(self):
        r = self.sell(amount=0, key='d0')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual((d['split']['total'], d['originalTotal'], d['status']), (0, 3500, 'awaiting_client'))
        with self.captureOnCommitCallbacks(execute=True):
            a = self.api.post(f'/api/v1/cashback-requests/{d["id"]}/approve', HTTP_IDEMPOTENCY_KEY='x0')
        self.assertEqual(a.status_code, 200, a.content)
        req = CashbackRequest.objects.get(pk=d['id'])
        self.assertEqual((req.points, req.cashback), (0, 0))
        self.assertIn(req.status, ('confirmed', 'credited'))

    def _cash(self, path, **data):
        spa = Category.objects.get(pk='spa')
        if 'cash' not in spa.methods:
            spa.methods = list(spa.methods) + ['cash']
            spa.save()
        with self.captureOnCommitCallbacks(execute=True):
            return self.desk.post(f'{S}/cash/{path}', {'payToken': self.pay_token, 'itemId': 'spa-stone',
                                                       'receiptQr': GNS_QR, **data}, format='json')

    def test_cash_receipt_matches_discounted_amount(self):
        r = self._cash('preview', quantity=1, amount=2500)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['total'], r.json()['originalTotal']), (2500, 3500))
        r = self._cash('accept', quantity=1, amount=2500)
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual((d['split']['total'], d['originalTotal']), (2500, 3500))
        self.assertIsNotNone(d['cancelUntil'])

    def test_cash_receipt_mismatch(self):
        r = self._cash('preview', quantity=1, amount=2000)          # в чеке 2 500
        self.assertEqual((r.status_code, r.json()['error']['code']), (422, 'receipt_amount_mismatch'))
        self.assertEqual((r.json()['error']['amount'], r.json()['error']['expected']), (2500, 2000))
        r = self._cash('accept', quantity=1)                         # без amount — сверка с прайсом 3 500
        self.assertEqual(r.json()['error']['code'], 'receipt_amount_mismatch')
        self.assertEqual(r.json()['error']['expected'], 3500)

    @override_settings(RECEIPT_ALLOWED_TINS=['01604199910194'])
    def test_wrong_seller(self):
        for path in ('preview', 'accept'):
            r = self._cash(path, quantity=1, amount=2500)
            self.assertEqual((r.status_code, r.json()['error']['code']), (422, 'receipt_wrong_seller'), path)

    def test_tins_from_admin_settings(self):
        self.settings_obj(receipt_tins='01604199910194, 02000000000000')
        r = self._cash('preview', quantity=1, amount=2500)
        self.assertEqual(r.json()['error']['code'], 'receipt_wrong_seller')
        self.settings_obj(receipt_tins='21804199500937')
        self.assertEqual(self._cash('preview', quantity=1, amount=2500).status_code, 200)

    def test_discounts_report(self):
        self.sell(amount=2000, key='d2')
        owner = Client()
        owner.force_login(self.make_staff('owner', email='boss@b.kg'))
        r = owner.get('/panel/requests/discounts/')
        self.assertContains(r, '−43%')                               # 1 500 из 3 500
        self.assertContains(r, self.cashier.full_name)


class RestaurantClientOrderTests(BaseAPITestCase):
    """Рестораны (food): клиент не создаёт заявку и не платит в приложении — только кассир."""

    def test_client_cannot_order_food(self):
        member = self.make_member(points=50_000)
        self.auth(member)
        item = self.api.get('/api/v1/catalog').json()
        food = next(c for c in item if c['id'] == 'food')
        self.assertFalse(food['clientOrders'])
        self.assertFalse(food['items'][0]['clientOrder'])
        r = self.api.post('/api/v1/cashback-requests/quote', {'itemId': 'food-davinci', 'checkAmount': 2000},
                          format='json')
        self.assertEqual(r.json()['error']['code'], 'client_order_disabled')
        r = self.api.post('/api/v1/cashback-requests', {'itemId': 'food-davinci', 'checkAmount': 2000,
                                                        'method': 'cash'}, format='json',
                          HTTP_IDEMPOTENCY_KEY='f1')
        self.assertEqual(r.json()['error']['code'], 'client_order_disabled')
        spa = next(c for c in item if c['id'] == 'spa')
        self.assertTrue(spa['items'][0]['clientOrder'])
