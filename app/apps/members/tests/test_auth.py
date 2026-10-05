from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.common.testing import BaseAPITestCase
from apps.members.models import Consent, Device, Member, MemberStatus, OtpChallenge

A = '/api/v1/auth'


def last_code(phone):
    return cache.get(f'sms:last:{phone}').rsplit(' ', 1)[-1]


class OtpLoginTests(BaseAPITestCase):
    phone = '+996555111222'

    def request_code(self, phone=None):
        return self.api.post(f'{A}/otp/request', {'phone': phone or self.phone}, format='json')

    def verify(self, code, phone=None):
        return self.api.post(f'{A}/otp/verify', {'phone': phone or self.phone, 'code': code}, format='json')

    def register(self, token, **extra):
        data = {'registrationToken': token, 'firstName': 'Урмат', 'lastName': 'Асанов', 'birthday': '1994-05-14',
                'email': 'urmat@example.com', 'acceptTerms': True, 'marketingConsent': True, **extra}
        return self.api.post(f'{A}/register', data, format='json', HTTP_X_DEVICE_ID='3f1c1a2e-1111-4a1e-9c1b-0e1d2c3b4a59')

    def test_full_registration_flow(self):
        r = self.request_code()
        self.assertEqual(r.json(), {'expiresIn': 120, 'retryIn': 60})
        r = self.verify(last_code(self.phone))
        self.assertTrue(r.json()['isNew'])
        r = self.register(r.json()['registrationToken'])
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertIn('accessToken', d)
        self.assertRegex(d['profile']['memberId'], r'^BT-\d{6}$')
        self.assertEqual(d['profile']['pendingConsents'], [])
        m = Member.objects.get(phone=self.phone)
        self.assertEqual(m.wallet.balance, 0)
        self.assertEqual(m.wallet.tier_id, 'bronze')
        self.assertEqual(set(Consent.objects.filter(member=m).values_list('kind', flat=True)),
                         {'terms', 'privacy', 'marketing'})
        # повторный вход — сразу токены
        cache.clear()
        OtpChallenge.objects.all().delete()
        self.request_code()
        r = self.verify(last_code(self.phone))
        self.assertIn('accessToken', r.json())

    def test_retry_limit_and_wrong_code_burns(self):
        self.request_code()
        r = self.request_code()
        self.assertEqual((r.status_code, r.json()['error']['code']), (429, 'otp_too_often'))
        for _ in range(4):
            self.assertEqual(self.verify('0000').json()['error']['code'], 'otp_invalid')
        self.assertEqual(self.verify('0000').json()['error']['code'], 'otp_expired')  # 5-я ошибка сжигает код
        code = last_code(self.phone)
        self.assertEqual(self.verify(code).json()['error']['code'], 'otp_expired')

    def test_expired_code(self):
        self.request_code()
        OtpChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify(last_code(self.phone)).json()['error']['code'], 'otp_expired')

    def test_register_multipart_with_optional_avatar(self):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (100, 100), 'green').save(buf, 'PNG')
        self.request_code()
        token = self.verify(last_code(self.phone)).json()['registrationToken']
        r = self.api.post(f'{A}/register', {
            'registrationToken': token, 'firstName': 'Айгуль', 'lastName': 'Токтогулова', 'birthday': '1995-03-01',
            'acceptTerms': 'true', 'marketingConsent': 'false',
            'avatar': SimpleUploadedFile('me.png', buf.getvalue(), content_type='image/png')}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNotNone(r.json()['profile']['avatar'])
        self.assertFalse(r.json()['profile']['marketingConsent'])

    def test_register_validation(self):
        self.request_code()
        token = self.verify(last_code(self.phone)).json()['registrationToken']
        self.assertEqual(self.register(token, acceptTerms=False).json()['error']['code'], 'terms_required')
        young = (timezone.localdate() - timedelta(days=365 * 15)).isoformat()
        self.assertEqual(self.register(token, birthday=young).json()['error']['code'], 'age_restricted')
        r = self.register(token, firstName='', email='bad')
        self.assertEqual(r.json()['error']['code'], 'validation_error')
        self.assertEqual(self.register('forged').json()['error']['code'], 'registration_expired')

    def test_phone_validation(self):
        r = self.request_code('12')
        self.assertEqual(r.json()['error']['code'], 'phone_invalid')

    def test_store_test_phone_fixed_code_no_sms(self):
        self.settings_obj(test_enabled=True, test_phone='+996700000000', test_code='1234')
        self.request_code('+996700000000')
        self.assertIsNone(cache.get('sms:last:+996700000000'))
        self.assertTrue(self.verify('1234', '+996700000000').json()['isNew'])

    def test_fixed_otp_code_on_staging(self):
        from django.test import override_settings
        with override_settings(OTP_FIXED_CODE='1234', APP_ENV='staging'):
            self.request_code('+996555999000')
            self.assertTrue(self.verify('1234', '+996555999000').json()['isNew'])
        cache.clear()
        OtpChallenge.objects.all().delete()
        with override_settings(OTP_FIXED_CODE='1234', APP_ENV='production'):
            self.request_code('+996555999001')
            self.assertEqual(self.verify('1234', '+996555999001').json()['error']['code'], 'otp_invalid')

    def test_blocked_member(self):
        self.make_member(phone=self.phone, status=MemberStatus.BLOCKED)
        self.request_code()
        r = self.verify(last_code(self.phone))
        self.assertEqual((r.status_code, r.json()['error']['code']), (403, 'account_blocked'))

    def test_refresh_rotation_and_reuse_detection(self):
        m = self.make_member(phone=self.phone)
        tokens = self.auth(m)
        r = self.api.post(f'{A}/refresh', {'refreshToken': tokens['refreshToken']}, format='json')
        new = r.json()
        self.assertNotEqual(new['refreshToken'], tokens['refreshToken'])
        # старый сразу недействителен; повтор отзывает всю цепочку
        r = self.api.post(f'{A}/refresh', {'refreshToken': tokens['refreshToken']}, format='json')
        self.assertEqual(r.status_code, 401)
        r = self.api.post(f'{A}/refresh', {'refreshToken': new['refreshToken']}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_logout_revokes_and_unlinks_device(self):
        m = self.make_member(phone=self.phone)
        tokens = self.auth(m)
        self.api.post('/api/v1/me/devices', {'token': 'fcm-1', 'platform': 'ios', 'appVersion': '0.1.0'}, format='json')
        self.assertEqual(Device.objects.count(), 1)
        self.api.post(f'{A}/logout', {'refreshToken': tokens['refreshToken'], 'pushToken': 'fcm-1'}, format='json')
        self.assertEqual(Device.objects.count(), 0)
        self.assertEqual(self.api.post(f'{A}/refresh', {'refreshToken': tokens['refreshToken']},
                                       format='json').status_code, 401)


class ProfileTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(birthday=None)
        self.auth(self.member)

    def test_me_shape(self):
        d = self.api.get('/api/v1/me').json()
        self.assertEqual(set(d), {'avatar', 'firstName', 'lastName', 'phone', 'email', 'birthday', 'memberId', 'memberSince',
                                  'settings', 'marketingConsent', 'pendingConsents', 'socialAccounts', 'hasPin'})

    def test_avatar_upload_replace_delete(self):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from apps.common.models import Upload

        def photo(w, h):
            buf = io.BytesIO()
            Image.new('RGB', (w, h), 'blue').save(buf, 'JPEG')
            return SimpleUploadedFile('a.jpg', buf.getvalue(), content_type='image/jpeg')

        self.assertIsNone(self.api.get('/api/v1/me').json()['avatar'])
        r = self.api.post('/api/v1/me/avatar', {'file': photo(800, 600)}, format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['avatar'].endswith('.jpg'))
        up = Upload.objects.get(kind='avatar')
        with up.file.open('rb') as fh:
            self.assertEqual(Image.open(fh).size, (512, 512))
        self.api.post('/api/v1/me/avatar', {'file': photo(300, 300)}, format='multipart')
        self.assertEqual(Upload.objects.filter(kind='avatar').count(), 1)   # старый удалён
        bad = SimpleUploadedFile('a.txt', b'not an image', content_type='text/plain')
        self.assertEqual(self.api.post('/api/v1/me/avatar', {'file': bad}, format='multipart')
                         .json()['error']['code'], 'file_invalid')
        self.assertIsNone(self.api.delete('/api/v1/me/avatar').json()['avatar'])
        self.assertEqual(Upload.objects.filter(kind='avatar').count(), 0)

    def test_birthday_set_once(self):
        r = self.api.patch('/api/v1/me', {'birthday': '1990-01-02'}, format='json')
        self.assertEqual(r.json()['birthday'], '1990-01-02')
        r = self.api.patch('/api/v1/me', {'birthday': '1990-01-09'}, format='json')
        self.assertEqual((r.status_code, r.json()['error']['code']), (403, 'birthday_locked'))

    def test_phone_is_not_editable(self):
        self.assertEqual(self.api.patch('/api/v1/me', {'phone': '+996700111222'}, format='json').status_code, 403)

    def test_settings_and_marketing_consent(self):
        r = self.api.patch('/api/v1/me/settings', {'language': 'ky', 'notifyPromos': True}, format='json')
        self.assertEqual(r.json(), {'language': 'ky', 'notifyCashback': True, 'notifyPromos': True})
        self.member.refresh_from_db()
        self.assertTrue(self.member.marketing_consent)

    def test_new_terms_version_requires_acceptance(self):
        from apps.members.models import LegalDocument
        LegalDocument.objects.create(kind='terms', version='2.0', url={'ru': 'https://x/terms2'},
                                     published_at=timezone.now())
        pending = self.api.get('/api/v1/me').json()['pendingConsents']
        self.assertEqual(pending[0]['version'], '2.0')
        r = self.api.post('/api/v1/me/consents', {'kind': 'terms', 'version': '2.0'}, format='json')
        self.assertEqual(r.json()['pendingConsents'], [p for p in pending if p['kind'] != 'terms'])

    def test_summary_and_member_qr(self):
        self.assertEqual(self.api.get('/api/v1/me/summary').json(), {'available': 0, 'current': 0, 'lifetime': 0,
                                                                    'requestsCount': 0})
        qr = self.api.get('/api/v1/me/member-qr').json()
        from apps.members.auth import read_member_qr
        self.assertEqual(read_member_qr(qr['token']).pk, self.member.pk)


class DeletionTests(BaseAPITestCase):
    phone = '+996555333444'

    def setUp(self):
        super().setUp()
        self.member = self.make_member(phone=self.phone, points=50_000)
        self.tokens = self.auth(self.member)

    def delete_account(self):
        r = self.api.post('/api/v1/me/deletion/request')
        self.assertEqual(r.json()['balance'], 50_000)
        r = self.api.post('/api/v1/me/deletion/confirm', {'code': last_code(self.phone)}, format='json')
        self.assertEqual(r.json(), {'deleted': True})

    def test_deactivate_then_restore(self):
        self.delete_account()
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, MemberStatus.DEACTIVATED)
        self.assertAlmostEqual((self.member.purge_at - self.member.deleted_at).days, 30)
        # токены отозваны
        self.assertEqual(self.api.get('/api/v1/me').status_code, 401)
        # вход по тому же номеру → предложение восстановить
        cache.clear()
        OtpChallenge.objects.all().delete()
        self.api.credentials()
        self.api.post(f'{A}/otp/request', {'phone': self.phone}, format='json')
        d = self.api.post(f'{A}/otp/verify', {'phone': self.phone, 'code': last_code(self.phone)}, format='json').json()
        self.assertTrue(d['deactivated'])
        self.assertEqual(d['balance'], 50_000)
        r = self.api.post(f'{A}/restore', {'restoreToken': d['restoreToken']}, format='json')
        self.assertEqual(r.status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, MemberStatus.ACTIVE)
        self.assertEqual(self.wallet(self.member).balance, 50_000)

    def test_start_over_purges_and_frees_phone(self):
        self.delete_account()
        from apps.members.auth import make_restore_token
        self.api.credentials()
        r = self.api.post(f'{A}/restart', {'restoreToken': make_restore_token(self.member)}, format='json')
        self.assertTrue(r.json()['isNew'])
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, MemberStatus.PURGED)
        self.assertIsNone(self.member.phone)
        self.assertEqual(self.wallet(self.member).balance, 0)
        self.assertTrue(self.member.operations.filter(kind='forfeit', points=-50_000).exists())

    def test_purge_after_30_days_postponed_by_active_request(self):
        from apps.cashback import services as cs
        from apps.members.services import purge_due_members
        req, _ = cs.create_request(self.member, {'itemId': 'room-deluxe', 'quantity': 1, 'method': 'cash'})
        self.delete_account()
        later = timezone.now() + timedelta(days=31)
        self.assertEqual(purge_due_members(later), {'purged': 0, 'postponed': 1})
        cs.confirm_request(req.pk)
        cs.credit_request(req.pk)                     # кешбек ложится на замороженный кошелёк
        self.assertEqual(self.wallet(self.member).balance, 50_000 + 23_000 * 7)
        self.assertEqual(purge_due_members(later + timedelta(days=2)), {'purged': 1, 'postponed': 0})
        self.member.refresh_from_db()
        self.assertEqual(self.member.full_name, 'Удалённый участник')
        req.refresh_from_db()
        self.assertEqual(req.member_id, self.member.pk)   # заявка осталась обезличенной

    def test_web_deletion_page(self):
        from django.test import Client
        c = Client()
        c.post('/account/delete', {'step': 'phone', 'phone': self.phone})
        r = c.post('/account/delete', {'step': 'code', 'code': last_code(self.phone)})
        self.assertContains(r, 'Аккаунт удалён')
        self.member.refresh_from_db()
        self.assertEqual(self.member.status, MemberStatus.DEACTIVATED)

