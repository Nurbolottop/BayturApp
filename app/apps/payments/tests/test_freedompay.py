from unittest import mock

from django.test import override_settings

from apps.cashback import services as cs
from apps.common.testing import BaseAPITestCase
from apps.payments.gateways import freedompay_sig
from apps.payments.models import Payment, Refund

SECRET = 'fp-secret'


def xml(**fields):
    body = ''.join(f'<{k}>{v}</{k}>' for k, v in fields.items())
    return mock.Mock(status_code=200, content=f'<?xml version="1.0"?><response>{body}</response>'.encode(),
                     raise_for_status=lambda: None)


@override_settings(FREEDOMPAY_MERCHANT_ID='545', FREEDOMPAY_SECRET_KEY=SECRET)
class FreedomPayTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=500_000)
        self.auth(self.member)
        patcher = mock.patch('apps.payments.gateways.requests.post')
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        self.post.return_value = xml(pg_status='ok', pg_payment_id='777', pg_redirect_url='https://pay.fp/777')

    def pay(self, method='freedomPay'):
        data = {'method': method, 'amountSom': 7000, 'itemId': 'spa-stone', 'quantity': 2}
        return self.api.post('/api/v1/payments', data, format='json')

    def callback(self, payment, result='1', amount='7000.00', can_reject='1', secret=SECRET):
        params = {'pg_order_id': payment['id'], 'pg_payment_id': '777', 'pg_amount': amount, 'pg_currency': 'KGS',
                  'pg_result': result, 'pg_can_reject': can_reject, 'pg_salt': 'abc'}
        params['pg_sig'] = freedompay_sig('freedompay', params, secret)
        return self.client.post('/api/v1/payments/webhooks/freedompay', params)

    def test_init_payment_signed_request(self):
        r = self.pay()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['redirectUrl'], 'https://pay.fp/777')
        url, = self.post.call_args.args
        sent = self.post.call_args.kwargs['data']
        self.assertEqual(url, 'https://api.freedompay.kg/init_payment.php')
        self.assertEqual(sent['pg_sig'], freedompay_sig('init_payment.php', sent, SECRET))
        self.assertEqual((sent['pg_amount'], sent['pg_currency'], sent['pg_order_id']), (7000, 'KGS', r.json()['id']))
        self.assertEqual(sent['pg_result_url'], 'https://api.test/api/v1/payments/webhooks/freedompay')
        p = Payment.objects.get(pk=r.json()['id'])
        self.assertEqual((p.provider, p.provider_ref), ('freedompay', '777'))

    def test_page_in_member_language_with_email_and_quantity(self):
        self.member.language, self.member.email = 'ky', 'guest@example.com'
        self.member.save()
        self.pay()
        sent = self.post.call_args.kwargs['data']
        self.assertEqual((sent['pg_language'], sent['pg_user_contact_email']), ('kg', 'guest@example.com'))
        self.assertTrue(sent['pg_description'].startswith('BAYTUR: ') and sent['pg_description'].endswith(' × 2'))

    def test_other_methods_stay_on_backend(self):
        self.assertTrue(self.pay(method='elqr').json()['qrPayload'])
        self.post.assert_not_called()

    def test_init_error_returns_503(self):
        self.post.return_value = xml(pg_status='error', pg_error_description='bad merchant')
        r = self.pay()
        self.assertEqual((r.status_code, r.json()['error']['code']), (503, 'payment_unavailable'))
        self.assertEqual(Payment.objects.get().status, 'failed')

    def test_result_callback(self):
        p = self.pay().json()
        self.assertEqual(self.callback(p, secret='wrong').status_code, 401)
        r = self.callback(p)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'<pg_status>ok</pg_status>', r.content)
        self.assertEqual(Payment.objects.get(pk=p['id']).status, 'paid')
        self.assertIn(b'<pg_status>ok</pg_status>', self.callback(p).content)  # повтор — идемпотентно

    def test_failed_callback(self):
        p = self.pay().json()
        self.callback(p, result='0')
        self.assertEqual(Payment.objects.get(pk=p['id']).status, 'failed')

    def test_amount_mismatch_rejected(self):
        p = self.pay().json()
        r = self.callback(p, amount='1.00')
        self.assertIn(b'<pg_status>rejected</pg_status>', r.content)
        self.assertEqual(Payment.objects.get(pk=p['id']).status, 'failed')

    def test_check_and_refund(self):
        p = self.pay().json()
        self.post.return_value = xml(pg_status='ok', pg_payment_status='success', pg_amount='7000')
        self.assertEqual(self.api.post(f'/api/v1/payments/{p["id"]}/check').json()['status'], 'paid')
        self.assertTrue(self.post.call_args.args[0].endswith('/get_status3.php'))
        req, _ = cs.create_request(self.member, {'itemId': 'spa-stone', 'quantity': 2, 
                                                 'method': 'freedomPay', 'paymentId': p['id']})
        self.post.return_value = xml(pg_status='ok')
        with self.captureOnCommitCallbacks(execute=True):
            cs.adjust_request(req.pk, 6000)
        sent = self.post.call_args.kwargs['data']
        self.assertTrue(self.post.call_args.args[0].endswith('/revoke.php'))
        self.assertEqual((sent['pg_payment_id'], sent['pg_refund_amount']), ('777', 1000))
        self.assertEqual(Refund.objects.get().status, 'done')

    def test_return_page_deeplinks(self):
        p = self.pay().json()
        r = self.client.get(f'/api/v1/payments/{p["id"]}/return')
        self.assertContains(r, f'baytur://payment/{p["id"]}')
        self.assertContains(r, 'Проверяем оплату')
        self.callback(p)
        self.assertContains(self.client.get(f'/api/v1/payments/{p["id"]}/return'), 'Оплата прошла')
        self.member.language = 'ky'
        self.member.save()
        self.assertContains(self.client.get(f'/api/v1/payments/{p["id"]}/return'), 'Төлөм өттү')

    @override_settings(FREEDOMPAY_MERCHANT_ID='')
    def test_disabled_falls_back(self):
        self.assertTrue(self.pay().json()['redirectUrl'].endswith('/checkout'))
        self.assertEqual(self.client.post('/api/v1/payments/webhooks/freedompay', {}).status_code, 404)
