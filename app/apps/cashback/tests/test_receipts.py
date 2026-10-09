from unittest import mock

from apps.cashback.models import CashbackRequest, FiscalReceipt, RequestStatus
from apps.cashback.receipts import parse_receipt
from apps.catalog.models import Item
from apps.common.errors import ApiError
from apps.common.testing import BaseAPITestCase
from apps.members.auth import make_member_qr

S = '/api/v1/staff'
GNS_QR = ('https://tax.salyk.kg/tax-web-control/client/ticket?tin=21804199500937&fn_number=0000000002300267'
          '&fd_number=99340&type=1&date=20261008T030337&sum=250000')  # 2500,00 сом в тыйынах


class ParseReceiptTests(BaseAPITestCase):
    def test_salyk_receipt_sum_in_tyiyn(self):
        r = parse_receipt(GNS_QR)
        self.assertEqual(r['amount'], 2500)
        self.assertEqual(r['key'], 'salyk:21804199500937:0000000002300267:99340')
        # реальный чек с фото: ИТОГО 240,00 → sum=24000
        r = parse_receipt('https://tax.salyk.kg/x?tin=21804199500937&fn_number=0000000002300267&fd_number=99340'
                          '&type=1&sum=24000')
        self.assertEqual(r['amount'], 240)
        self.assertEqual(parse_receipt('https://tax.salyk.kg/x?tin=1&fn_number=2&fd_number=3&sum=24050')['amount'], 241)

    def test_salyk_needs_ids_and_integer_sum(self):
        for raw in ('https://tax.salyk.kg/x?tin=1&fn_number=2&sum=24000',      # нет ФД
                    'https://tax.salyk.kg/x?tin=1&fn_number=2&fd_number=3&sum=abc'):
            with self.assertRaises(ApiError, msg=raw):
                parse_receipt(raw)

    def test_plain_pairs_and_rounding(self):
        r = parse_receipt('t=20261008T1215&s=1499,50&fn=111&i=22&fp=333&n=1')
        self.assertEqual(r['amount'], 1500)
        self.assertIn('fn=111', r['key'])
        self.assertNotIn('n=1', r['key'].split('|'))

    def test_no_ids_falls_back_to_hash(self):
        self.assertTrue(parse_receipt('https://example.kg/check?sum=100').get('key').startswith('sha256:'))

    def test_unreadable(self):
        for raw in ('', 'hello', 'https://x.kg/?sum=0', 'https://x.kg/?sum=abc', 'x' * 3000):
            with self.assertRaises(ApiError, msg=raw):
                parse_receipt(raw)


class DeskReceiptTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.item = Item.objects.select_related('category', 'outlet').get(pk='food-davinci')  # «по сумме чека»
        cats = self.item.category
        if 'cash' not in cats.methods:
            cats.methods = list(cats.methods) + ['cash']
            cats.save()
        self.cashier = self.make_staff('staff', outlets=[self.item.outlet])
        self.client_ = self.staff_client(self.cashier)
        self.member = self.make_member('+996555101010', points=50_000)

    def scan(self):
        token, _ = make_member_qr(self.member)
        r = self.client_.post(f'{S}/scan', {'token': token}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_scan_shows_points(self):
        d = self.scan()
        self.assertEqual(d['points'], 50_000)
        self.assertEqual(d['pointsSom'], 5_000)       # 10 баллов = 1 сом
        self.assertIn('payToken', d)

    def test_preview_accept_and_duplicate(self):
        pay = self.scan()['payToken']
        body = {'payToken': pay, 'itemId': self.item.pk, 'receiptQr': GNS_QR, 'requestId': None}  # null = без заявки
        r = self.client_.post(f'{S}/cash/preview', body, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['amount'], r.json()['total']), (2500, 2500))
        self.assertGreater(r.json()['cashback'], 0)
        self.assertFalse(FiscalReceipt.objects.exists())  # предпросмотр ничего не сохраняет

        with self.captureOnCommitCallbacks(execute=True):
            r = self.client_.post(f'{S}/cash/accept', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(d['fiscalReceipt']['amount'], 2500)
        self.assertEqual(d['fiscalReceipt']['acceptedBy'], self.cashier.pk)
        self.assertIn('acceptedByName', d['fiscalReceipt'])
        req = CashbackRequest.objects.get(pk=d['id'])
        self.assertIn(req.status, (RequestStatus.CONFIRMED, RequestStatus.CREDITED))
        self.assertEqual((req.method, req.money_som, req.confirmed_by_id), ('cash', 2500, self.cashier.pk))

        # тот же чек повторно — и в предпросмотре, и при приёме
        for url in ('preview', 'accept'):
            r = self.client_.post(f'{S}/cash/{url}', body, format='json')
            self.assertEqual((r.status_code, r.json()['error']['code']), (409, 'receipt_used'), url)
            self.assertEqual(r.json()['error']['requestId'], req.pk)
            self.assertEqual((r.json()['error']['acceptedBy'], r.json()['error']['acceptedByName']),
                             (self.cashier.pk, self.cashier.full_name or None))
        self.assertEqual(FiscalReceipt.objects.count(), 1)

    def test_attaches_to_client_cash_request(self):
        r = self.auth(self.member)
        r = self.api.post('/api/v1/cashback-requests', {'itemId': self.item.pk, 'checkAmount': 2000, 'method': 'cash'},
                          format='json', HTTP_IDEMPOTENCY_KEY='k-1')
        self.assertEqual(r.status_code, 201, r.content)
        request_id = r.json()['id']
        pay = self.scan()['payToken']
        r = self.client_.post(f'{S}/cash/accept', {'payToken': pay, 'itemId': self.item.pk, 'receiptQr': GNS_QR,
                                                   'requestId': request_id}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['id'], request_id)
        req = CashbackRequest.objects.get(pk=request_id)
        self.assertEqual((req.total, req.original_total), (2500, 2000))  # сумма — по чеку
        self.assertEqual(CashbackRequest.objects.filter(member=self.member).count(), 1)

    def test_unreadable_and_stale_pay_token(self):
        pay = self.scan()['payToken']
        r = self.client_.post(f'{S}/cash/preview', {'payToken': pay, 'itemId': self.item.pk, 'receiptQr': 'abc'},
                              format='json')
        self.assertEqual(r.json()['error']['code'], 'receipt_unreadable')
        r = self.client_.post(f'{S}/cash/accept', {'payToken': 'bad', 'itemId': self.item.pk, 'receiptQr': GNS_QR},
                              format='json')
        self.assertEqual(r.json()['error']['code'], 'qr_invalid')


class StaffPushTests(BaseAPITestCase):
    def test_device_register_and_online_payment_push(self):
        from apps.notifications.services import notify_staff_paid_online
        from apps.staff.models import StaffDevice
        item = Item.objects.active().first()
        cashier = self.make_staff('staff', outlets=[item.outlet])
        other = self.make_staff('staff')  # чужая точка — не получает
        for user, token in ((cashier, 'tok-a'), (other, 'tok-b')):
            r = self.staff_client(user).post(f'{S}/me/devices', {'token': token, 'platform': 'android'}, format='json')
            self.assertEqual(r.status_code, 204, r.content)
        self.assertEqual(StaffDevice.objects.count(), 2)
        member = self.make_member('+996555202020')
        req = CashbackRequest.objects.create(
            member=member, item=item, outlet=item.outlet, item_snapshot=item.snapshot(), rules={'rate': '0.05'},
            total=8000, points_som=0, points=0, money_som=8000, rate='0.05', cashback=40000, method='freedomPay')
        sent = []
        with mock.patch('apps.notifications.push.ConsoleBackend.send',
                        side_effect=lambda token, *a: sent.append((token, a[1])) or (True, False)):
            self.assertEqual(notify_staff_paid_online(req.pk), 1)
        self.assertEqual(sent[0][0], 'tok-a')
        self.assertIn('8 000 сом', sent[0][1])
