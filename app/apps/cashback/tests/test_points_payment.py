from apps.cashback.models import CashbackRequest
from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Operation

S = '/api/v1/staff'


class PointsPaymentTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=500_000)          # 5 000 сом
        self.spa_staff = self.make_staff('staff', outlets=['spa'])
        self.spa = self.staff_client(self.spa_staff)
        self.auth(self.member)
        qr = self.api.get('/api/v1/me/member-qr').json()['token']
        self.pay_token = self.spa.post(f'{S}/scan', {'token': qr}, format='json').json()['payToken']

    def pay(self, path, **data):
        return self.spa.post(f'{S}/points/{path}', {'payToken': self.pay_token, **data}, format='json')

    def test_quote_and_charge(self):
        items = [i['id'] for i in self.spa.get(f'{S}/points/items').json()['items']]
        self.assertIn('spa-stone', items)
        self.assertNotIn('food-davinci', items)                  # только услуги своей точки
        q = self.pay('quote', itemId='spa-stone', quantity=1).json()
        self.assertEqual((q['total'], q['points'], q['enough']), (3500, 350_000, True))
        self.assertNotIn('available', q)                         # баланс сотруднику не показываем
        with self.captureOnCommitCallbacks(execute=True):
            r = self.pay('charge', itemId='spa-stone', quantity=1)
        self.assertEqual(r.status_code, 201, r.content)
        req = CashbackRequest.objects.get(pk=r.json()['id'])
        self.assertEqual((req.status, req.points, req.money_som, req.method, req.confirmed_by_id),
                         ('confirmed', 350_000, 0, None, self.spa_staff.pk))
        self.assertEqual(Operation.objects.get(request=req, kind='spend').points, -350_000)
        self.assertEqual(self.wallet(self.member).balance, 150_000)

    def test_not_enough_points(self):
        q = self.pay('quote', itemId='spa-stone', quantity=2).json()  # 7 000 сом > 5 000
        self.assertEqual((q['enough'], q['shortSom'], q['reason']), (False, 2000, 'balance'))
        r = self.pay('charge', itemId='spa-stone', quantity=2)
        self.assertEqual((r.status_code, r.json()['error']['code']), (422, 'insufficient_points'))
        self.assertFalse(CashbackRequest.objects.exists())       # ничего не создано и не зарезервировано
        self.assertEqual(self.wallet(self.member).reserved, 0)

    def test_category_limit_reason(self):
        reception = self.staff_client(self.make_staff('staff', outlets=['reception']))
        self.auth(self.member)
        qr = self.api.get('/api/v1/me/member-qr').json()['token']
        token = reception.post(f'{S}/scan', {'token': qr}, format='json').json()['payToken']
        q = reception.post(f'{S}/points/quote', {'payToken': token, 'itemId': 'pools-kids', 'quantity': 1},
                           format='json').json()
        self.assertTrue(q['enough'])
        rich = self.make_member(phone='+996555000444', points=10_000_000)
        self.auth(rich)
        qr = self.api.get('/api/v1/me/member-qr').json()['token']
        token = reception.post(f'{S}/scan', {'token': qr}, format='json').json()['payToken']
        q = reception.post(f'{S}/points/quote', {'payToken': token, 'itemId': 'room-deluxe', 'quantity': 1},
                           format='json').json()
        self.assertEqual((q['enough'], q['reason'], q['limitPercent']), (False, 'limit', 30))

    def test_token_bound_to_staff_and_own_account(self):
        other = self.staff_client(self.make_staff('staff', outlets=['spa']))
        r = other.post(f'{S}/points/charge', {'payToken': self.pay_token, 'itemId': 'spa-stone', 'quantity': 1},
                       format='json')
        self.assertEqual(r.json()['error']['code'], 'qr_invalid')
        self.spa_staff.phone = self.member.phone
        self.spa_staff.save()
        r = self.pay('charge', itemId='spa-stone', quantity=1)
        self.assertEqual(r.json()['error']['code'], 'own_account')
        self.assertFalse(CashbackRequest.objects.exists())

    def test_client_gets_paid_notification(self):
        from apps.cashback.services import credit_request
        with self.captureOnCommitCallbacks(execute=True):
            req_id = self.pay('charge', itemId='spa-stone', quantity=1).json()['id']
            credit_request(req_id)
        n = self.member.notifications.filter(kind='request.paid').first()
        self.assertIsNotNone(n)
        self.assertIn('350 000', n.body)
        self.assertFalse(self.member.notifications.filter(kind='request.credited').exists())

    def test_panel_scan_and_charge(self):
        c = self.client
        c.force_login(self.spa_staff)
        self.auth(self.member)
        qr = self.api.get('/api/v1/me/member-qr').json()['token']
        page = c.post('/panel/desk/scan/', {'token': qr})
        self.assertContains(page, 'Оплата баллами')
        token = page.context['pay_token']
        q = c.post('/panel/desk/pay/quote/', {'pay_token': token, 'item': 'spa-stone', 'quantity': 1}).json()
        self.assertTrue(q['enough'])
        r = c.post('/panel/desk/pay/charge/', {'pay_token': token, 'item': 'spa-stone', 'quantity': 1})
        self.assertContains(r, 'Оплачено баллами')
        self.assertEqual(self.wallet(self.member).balance, 150_000)
