from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.common.testing import BaseAPITestCase
from apps.coupons import services
from apps.coupons.models import Coupon, WelcomeOffer

A = '/api/v1/auth'


class WelcomeCouponTests(BaseAPITestCase):
    phone = '+996555777001'

    def enable(self, **extra):
        o = WelcomeOffer.get()
        o.enabled, o.kind, o.value, o.valid_days = True, 'percent', 10, 30
        o.title = {'ru': 'Скидка 10% на первое проживание', 'ky': '', 'en': '10% off your first stay'}
        for k, v in extra.items():
            setattr(o, k, v)
        o.save()
        return o

    def register(self, phone=None):
        phone = phone or self.phone
        self.api.post(f'{A}/otp/request', {'phone': phone}, format='json')
        code = cache.get(f'sms:last:{phone}').rsplit(' ', 1)[-1]
        token = self.api.post(f'{A}/otp/verify', {'phone': phone, 'code': code}, format='json').json()['registrationToken']
        r = self.api.post(f'{A}/register', {'registrationToken': token, 'firstName': 'Аида', 'lastName': 'Т',
                                            'birthday': '1995-03-01', 'acceptTerms': True}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {r.json()["accessToken"]}')
        return r

    def test_disabled_by_default(self):
        self.assertFalse(WelcomeOffer.get().enabled)
        self.register()
        self.assertEqual(self.api.get('/api/v1/me/coupons').json()['items'], [])

    def test_issue_qr_scan_redeem(self):
        self.enable()
        self.register()
        items = self.api.get('/api/v1/me/coupons', HTTP_ACCEPT_LANGUAGE='en').json()['items']
        self.assertEqual(len(items), 1)
        c = items[0]
        self.assertEqual((c['kind'], c['value'], c['valueText'], c['status'], c['title']),
                         ('percent', 10, '−10%', 'active', '10% off your first stay'))
        token = self.api.get(f'/api/v1/me/coupons/{c["id"]}/qr').json()['token']
        cashier = self.staff_client(self.make_staff('staff', outlets=['reception']))
        card = cashier.post('/api/v1/staff/coupons/scan', {'token': token}, format='json').json()
        self.assertEqual((card['status'], card['member']['name']), ('active', 'Аида Т'))
        r = cashier.post('/api/v1/staff/coupons/redeem', {'token': token, 'note': 'бронь 15'}, format='json')
        self.assertEqual(r.json()['status'], 'redeemed')
        again = cashier.post('/api/v1/staff/coupons/redeem', {'token': token}, format='json')
        self.assertEqual((again.status_code, again.json()['error']['message']), (409, 'Купон уже использован'))
        self.assertEqual(self.api.get(f'/api/v1/me/coupons/{c["id"]}/qr').status_code, 409)

    def test_member_qr_shows_gifts_and_redeem_by_choice(self):
        self.enable(kind='gift', value=0, title={'ru': 'Бесплатный напиток', 'ky': '', 'en': ''})
        self.register()
        qr = self.api.get('/api/v1/me/member-qr').json()['token']
        cashier = self.staff_client(self.make_staff('staff', outlets=['reception']))
        scan = cashier.post('/api/v1/staff/scan', {'token': qr}, format='json').json()
        self.assertEqual([(c['title'], c['status']) for c in scan['coupons']], [('Бесплатный напиток', 'active')])
        body = {'payToken': scan['payToken'], 'couponId': scan['coupons'][0]['id']}
        r = cashier.post('/api/v1/staff/coupons/redeem', body, format='json')
        self.assertEqual((r.status_code, r.json()['status']), (200, 'redeemed'))
        self.assertEqual(cashier.post('/api/v1/staff/coupons/redeem', body, format='json').status_code, 409)
        scan = cashier.post('/api/v1/staff/scan', {'token': self.api.get('/api/v1/me/member-qr').json()['token']},
                            format='json').json()
        self.assertEqual(scan['coupons'], [])            # погашенный подарок клиенту больше не доступен
        other = self.staff_client(self.make_staff('staff', outlets=['reception'], phone='+996700111222'))
        bad = other.post('/api/v1/staff/coupons/redeem', body, format='json')  # payToken чужого кассира
        self.assertEqual(bad.json()['error']['code'], 'qr_invalid')

    def test_issued_realtime_event_and_push_data(self):
        from unittest import mock

        from apps.notifications.models import Notification
        self.enable()
        with mock.patch('apps.common.realtime.publish_member') as pub, self.captureOnCommitCallbacks(execute=True):
            self.register()
        coupon = Coupon.objects.get()
        events = {c.args[1]: c.args[2] for c in pub.call_args_list}
        self.assertEqual(events['coupon.issued']['id'], coupon.pk)
        n = Notification.objects.get(kind='coupon.issued')
        self.assertEqual(n.data, {'type': 'coupon.issued', 'couponId': coupon.pk})

    def test_once_per_phone_forever(self):
        from apps.members.models import Member
        from apps.members.services import purge
        self.enable()
        self.register()
        purge(Member.objects.get(phone=self.phone))
        from apps.members.models import OtpChallenge
        OtpChallenge.objects.all().delete()
        cache.clear()
        self.register()
        self.assertEqual(self.api.get('/api/v1/me/coupons').json()['items'], [])
        self.assertEqual(Coupon.objects.count(), 1)

    def test_expiry_and_conditions_snapshot(self):
        self.enable()
        self.register()
        coupon = Coupon.objects.get()
        offer = WelcomeOffer.get()
        offer.value = 50
        offer.save()
        coupon.refresh_from_db()
        self.assertEqual(coupon.value, 10)              # выданный купон хранит свои условия
        Coupon.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.api.get('/api/v1/me/coupons').json()['items'][0]['status'], 'expired')
        self.assertEqual(services.expire_coupons(), 1)

    def test_panel_settings_and_desk_redeem(self):
        owner = self.client
        owner.force_login(self.make_staff('owner', email='d@b.kg', superuser=True))
        r = owner.post('/panel/welcome/', {'enabled': 'on', 'kind': 'gift', 'value': 0, 'title_ru': 'Бесплатный ужин',
                                           'title_ky': '', 'title_en': '', 'description_ru': '', 'description_ky': '',
                                           'description_en': '', 'terms_ru': '', 'terms_ky': '', 'terms_en': '',
                                           'valid_days': 60})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(WelcomeOffer.get().enabled)
        self.register()
        coupon = Coupon.objects.get()
        token, _ = services.make_qr(coupon)
        page = owner.post('/panel/desk/scan/', {'token': token})
        self.assertContains(page, 'Бесплатный ужин')
        owner.post('/panel/desk/coupon/redeem/', {'token': token})
        coupon.refresh_from_db()
        self.assertEqual(coupon.status, 'redeemed')
