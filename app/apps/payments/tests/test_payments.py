import json
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from apps.cashback import services as cs
from apps.common.testing import BaseAPITestCase
from apps.payments import services
from apps.payments.gateways import sign
from apps.payments.models import Payment, WebhookEvent


class PaymentFlowTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=500_000)
        self.auth(self.member)

    def pay(self, amount=5500, method='finik', **extra):
        data = {'method': method, 'amountSom': amount, 'itemId': 'spa-stone', 'quantity': 2, 'pointsSom': 1500, **extra}
        return self.api.post('/api/v1/payments', data, format='json')

    def webhook(self, payment, status='paid', amount=None, secret='test-secret', event='e1'):
        body = json.dumps({'eventId': event, 'paymentId': payment['id'], 'status': status,
                           'amount': amount if amount is not None else payment['amount']}).encode()
        return self.api.post('/api/v1/payments/webhooks/fake', body, content_type='application/json',
                             HTTP_X_SIGNATURE=sign(body, secret))

    def test_amount_must_equal_money_part(self):
        r = self.pay(amount=5000)
        self.assertEqual(r.json()['error']['code'], 'payment_invalid')
        self.assertEqual(r.json()['error']['moneySom'], 5500)

    def test_redirect_and_qr(self):
        self.assertTrue(self.pay().json()['redirectUrl'].endswith('/checkout'))
        qr = self.pay(method='elqr').json()
        self.assertTrue(qr['qrPayload'])
        self.assertIsNotNone(qr['expiresAt'])

    def test_paid_payment_creates_request_and_refund_on_reject(self):
        p = self.pay().json()
        self.assertEqual(self.webhook(p, secret='wrong').status_code, 401)
        self.assertEqual(self.webhook(p).status_code, 200)
        self.assertEqual(self.webhook(p).status_code, 200)       # повтор — идемпотентно
        self.assertEqual(WebhookEvent.objects.count(), 1)
        self.assertEqual(self.api.get(f'/api/v1/payments/{p["id"]}').json()['status'], 'paid')
        r = self.api.post('/api/v1/cashback-requests', {'itemId': 'spa-stone', 'quantity': 2, 'pointsSom': 1500,
                                                       'method': 'finik', 'paymentId': p['id']}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        req = r.json()
        self.assertEqual(req['receipt']['amount'], 5500)
        # платёж нельзя привязать ко второй заявке
        r2 = self.api.post('/api/v1/cashback-requests', {'itemId': 'spa-stone', 'quantity': 2, 'pointsSom': 1500,
                                                        'method': 'finik', 'paymentId': p['id']}, format='json')
        self.assertEqual(r2.json()['error']['code'], 'payment_invalid')
        with self.captureOnCommitCallbacks(execute=True):
            cs.reject_request(req['id'], code='not_provided')
        payment = Payment.objects.get(pk=p['id'])
        self.assertEqual((payment.status, payment.refunded_amount), ('refunded', 5500))

    def test_amount_mismatch_in_webhook_fails_payment(self):
        p = self.pay().json()
        self.webhook(p, amount=1)
        self.assertEqual(Payment.objects.get(pk=p['id']).status, 'failed')

    def test_partial_refund_on_adjust_down(self):
        p = self.pay().json()
        self.webhook(p)
        req, _ = cs.create_request(self.member, {'itemId': 'spa-stone', 'quantity': 2, 'pointsSom': 1500,
                                                 'method': 'finik', 'paymentId': p['id']})
        with self.captureOnCommitCallbacks(execute=True):
            cs.adjust_request(req.pk, 6000)          # деньгами 4 500 вместо 5 500
        self.assertEqual(Payment.objects.get(pk=p['id']).refunded_amount, 1000)

    def test_orphan_paid_payment_gets_request(self):
        p = self.pay().json()
        self.webhook(p)
        Payment.objects.filter(pk=p['id']).update(paid_at=timezone.now() - timedelta(minutes=30))
        self.assertEqual(services.resolve_orphan_payments(), 1)
        payment = Payment.objects.get(pk=p['id'])
        self.assertIsNotNone(payment.request_id)
        self.assertEqual(payment.request.money_som, 5500)

    @mock.patch('apps.payments.services.refund_payment')
    def test_orphan_that_cannot_become_request_is_refunded(self, refund):
        p = self.pay().json()
        self.webhook(p)
        Payment.objects.filter(pk=p['id']).update(paid_at=timezone.now() - timedelta(minutes=30))
        from apps.catalog.models import Item
        Item.objects.filter(pk='spa-stone').update(is_active=False)
        services.resolve_orphan_payments()
        refund.assert_called_once()

    def test_expire(self):
        p = self.pay(method='elqr').json()
        Payment.objects.filter(pk=p['id']).update(expires_at=timezone.now() - timedelta(seconds=1))
        services.expire_payments()
        self.assertEqual(Payment.objects.get(pk=p['id']).status, 'expired')
