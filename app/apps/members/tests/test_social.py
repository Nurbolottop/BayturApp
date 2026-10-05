import hashlib
import time
from types import SimpleNamespace
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache
from django.test import override_settings

from apps.common.testing import BaseAPITestCase
from apps.members import services, social
from apps.members.models import Member, MemberStatus, SocialAccount

A = '/api/v1/auth'
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(provider='google', sub='g-1', key=KEY, **claims):
    iss = 'https://accounts.google.com' if provider == 'google' else 'https://appleid.apple.com'
    aud = 'web.apps.googleusercontent.com' if provider == 'google' else 'kg.baytur.app'
    payload = {'iss': iss, 'aud': aud, 'sub': sub, 'iat': int(time.time()), 'exp': int(time.time()) + 600,
               'email': f'{sub}@example.com', 'email_verified': True, **claims}
    return jwt.encode(payload, key, algorithm='RS256')


class FakeJwks:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


@override_settings(GOOGLE_CLIENT_IDS=['ios.apps.googleusercontent.com', 'web.apps.googleusercontent.com'],
                   APPLE_CLIENT_IDS=['kg.baytur.app'], OTP_FIXED_CODE='')
class SocialLoginTests(BaseAPITestCase):
    phone = '+996555333444'

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(social, '_jwks_client', lambda provider: FakeJwks())
        patcher.start()
        self.addCleanup(patcher.stop)

    def google(self, token=None):
        return self.api.post(f'{A}/google', {'idToken': token or make_token()}, format='json')

    def phone_step(self, social_token):
        cache.clear()
        self.api.post(f'{A}/otp/request', {'phone': self.phone}, format='json')
        code = cache.get(f'sms:last:{self.phone}').rsplit(' ', 1)[-1]
        return self.api.post(f'{A}/otp/verify', {'phone': self.phone, 'code': code, 'socialToken': social_token},
                             format='json')

    def register(self, registration_token):
        return self.api.post(f'{A}/register', {
            'registrationToken': registration_token, 'firstName': 'Айгуль', 'lastName': 'Токтогулова',
            'birthday': '1995-03-02', 'acceptTerms': True}, format='json')

    def test_new_user_google_then_phone_then_register_then_one_tap(self):
        r = self.google()
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertTrue(d['needPhone'])
        self.assertEqual(d['prefill']['email'], 'g-1@example.com')
        r = self.phone_step(d['socialToken'])
        self.assertTrue(r.json()['isNew'])
        r = self.register(r.json()['registrationToken'])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['profile']['socialAccounts'], ['google'])
        member = Member.objects.get(phone=self.phone)
        self.assertTrue(SocialAccount.objects.filter(member=member, provider='google', subject='g-1').exists())
        # дальше — вход в одно нажатие
        r = self.google()
        self.assertIn('accessToken', r.json())

    def test_existing_member_links_on_phone_confirm(self):
        member = self.make_member(self.phone)
        r = self.phone_step(self.google().json()['socialToken'])
        self.assertIn('accessToken', r.json())
        self.assertEqual(member.social_accounts.get().subject, 'g-1')

    def test_apple_nonce_and_name_prefill(self):
        nonce = 'raw-nonce'
        token = make_token('apple', 'a-1', nonce=hashlib.sha256(nonce.encode()).hexdigest(), email_verified='true')
        r = self.api.post(f'{A}/apple', {'identityToken': token, 'nonce': nonce, 'firstName': 'Айгуль'},
                          format='json')
        self.assertEqual(r.json()['prefill']['firstName'], 'Айгуль')
        r = self.api.post(f'{A}/apple', {'identityToken': token, 'nonce': 'other'}, format='json')
        self.assertEqual((r.status_code, r.json()['error']['code']), (401, 'social_invalid'))

    def test_rejects_bad_signature_audience_issuer_and_expired(self):
        bad = [make_token(key=OTHER_KEY), make_token(aud='someone-else'), make_token(iss='https://evil.example'),
               make_token(exp=int(time.time()) - 3600)]
        for token in bad:
            r = self.google(token)
            self.assertEqual((r.status_code, r.json()['error']['code']), (401, 'social_invalid'))
        # Google-токен на эндпоинт Apple не подходит
        r = self.api.post(f'{A}/apple', {'identityToken': make_token()}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_unverified_google_email_not_prefilled(self):
        r = self.google(make_token(email_verified=False))
        self.assertIsNone(r.json()['prefill']['email'])

    @override_settings(GOOGLE_CLIENT_IDS=[])
    def test_not_configured(self):
        r = self.google()
        self.assertEqual((r.status_code, r.json()['error']['code']), (503, 'social_unavailable'))

    def test_blocked_and_deactivated(self):
        member = self.make_member(self.phone)
        SocialAccount.objects.create(member=member, provider='google', subject='g-1')
        Member.objects.filter(pk=member.pk).update(status=MemberStatus.DEACTIVATED)
        self.assertTrue(self.google().json()['deactivated'])
        Member.objects.filter(pk=member.pk).update(status=MemberStatus.BLOCKED)
        self.assertEqual(self.google().status_code, 403)

    def test_purge_removes_link(self):
        member = self.make_member(self.phone)
        SocialAccount.objects.create(member=member, provider='google', subject='g-1')
        services.purge(member)
        self.assertFalse(SocialAccount.objects.exists())
        self.assertTrue(self.google().json()['needPhone'])

    def test_link_and_unlink_from_profile(self):
        member = self.make_member(self.phone)
        other = self.make_member('+996555000111')
        SocialAccount.objects.create(member=other, provider='google', subject='taken')
        self.auth(member)
        r = self.api.post('/api/v1/me/social/google', {'idToken': make_token(sub='taken')}, format='json')
        self.assertEqual((r.status_code, r.json()['error']['code']), (409, 'social_taken'))
        r = self.api.post('/api/v1/me/social/google', {'idToken': make_token(sub='mine')}, format='json')
        self.assertEqual(r.json()['socialAccounts'], ['google'])
        # повторная привязка другого Google-аккаунта заменяет прежний
        self.api.post('/api/v1/me/social/google', {'idToken': make_token(sub='mine-2')}, format='json')
        self.assertEqual(list(member.social_accounts.values_list('subject', flat=True)), ['mine-2'])
        r = self.api.delete('/api/v1/me/social/google')
        self.assertEqual(r.json()['socialAccounts'], [])


EC_KEY_FILE = None


def apple_key_file():
    """Настоящий EC-ключ P-256 в формате .p8 — проверяем, что client_secret подписывается."""
    global EC_KEY_FILE
    if EC_KEY_FILE is None:
        import tempfile
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        f = tempfile.NamedTemporaryFile('wb', suffix='.p8', delete=False)
        f.write(pem)
        f.close()
        EC_KEY_FILE = f.name
    return EC_KEY_FILE


class AppleResponse:
    def __init__(self, status=200, data=None, text=''):
        self.status_code, self._data, self.text = status, data or {}, text

    def json(self):
        return self._data

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(self.text)


@override_settings(APPLE_CLIENT_IDS=['kg.baytur.app'], APPLE_TEAM_ID='TEAM123456', APPLE_KEY_ID='KEY1234567',
                   OTP_FIXED_CODE='')
class AppleRevocationTests(BaseAPITestCase):
    phone = '+996555777888'

    def setUp(self):
        super().setUp()
        settings_patch = override_settings(APPLE_PRIVATE_KEY_FILE=apple_key_file())
        settings_patch.enable()
        self.addCleanup(settings_patch.disable)
        patcher = mock.patch.object(social, '_jwks_client', lambda provider: FakeJwks())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.posts = []

        def fake_post(url, data=None, timeout=None):
            self.posts.append((url, data))
            # client_secret — валидный ES256 JWT с нужными полями
            header = jwt.get_unverified_header(data['client_secret'])
            claims = jwt.decode(data['client_secret'], options={'verify_signature': False})
            assert header == {'alg': 'ES256', 'kid': 'KEY1234567', 'typ': 'JWT'}, header
            assert claims['iss'] == 'TEAM123456' and claims['sub'] == 'kg.baytur.app', claims
            if url.endswith('/auth/token'):
                return AppleResponse(data={'refresh_token': f'rt-{data["code"]}'})
            return AppleResponse()

        patcher = mock.patch('apps.members.social.requests.post', side_effect=fake_post)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('apps.members.tasks.revoke_apple_token.delay',
                             side_effect=lambda c, r: social.apple_revoke(c, r))
        patcher.start()
        self.addCleanup(patcher.stop)

    def apple(self, code='c1', sub='a-1'):
        return self.api.post(f'{A}/apple', {'identityToken': make_token('apple', sub), 'authorizationCode': code},
                             format='json')

    def revoked(self):
        return [d['token'] for url, d in self.posts if url.endswith('/auth/revoke')]

    def test_new_user_token_kept_until_link_then_revoked_on_deletion(self):
        social_token = self.apple().json()['socialToken']
        cache_key = services._apple_pending_key('a-1')
        from django.core.cache import cache
        pending = cache.get(cache_key)
        self.assertEqual(pending, ['kg.baytur.app', 'rt-c1'])
        # пользователь подтверждает номер (SMS-код в кеше — не чистим кеш, иначе потеряем токен Apple)
        self.api.post(f'{A}/otp/request', {'phone': self.phone}, format='json')
        code = cache.get(f'sms:last:{self.phone}').rsplit(' ', 1)[-1]
        r = self.api.post(f'{A}/otp/verify', {'phone': self.phone, 'code': code, 'socialToken': social_token},
                          format='json')
        r = self.api.post(f'{A}/register', {
            'registrationToken': r.json()['registrationToken'], 'firstName': 'А', 'lastName': 'Б',
            'birthday': '1995-03-02', 'acceptTerms': True}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        account = SocialAccount.objects.get(subject='a-1')
        self.assertEqual((account.client_id, account.refresh_token), ('kg.baytur.app', 'rt-c1'))
        self.assertIsNone(cache.get(cache_key))

        member = account.member
        with self.captureOnCommitCallbacks(execute=True):
            self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {r.json()["accessToken"]}')
            self.api.post('/api/v1/me/deletion/request', {}, format='json')
            code = cache.get(f'sms:last:{self.phone}').rsplit(' ', 1)[-1]
            r = self.api.post('/api/v1/me/deletion/confirm', {'code': code}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.revoked(), ['rt-c1'])
        account.refresh_from_db()
        self.assertEqual(account.refresh_token, '')  # привязка осталась для восстановления, токен забыт
        member.refresh_from_db()
        self.assertEqual(member.status, MemberStatus.DEACTIVATED)

    def test_relogin_replaces_token_and_revokes_old(self):
        member = self.make_member(self.phone)
        SocialAccount.objects.create(member=member, provider='apple', subject='a-1', client_id='kg.baytur.app',
                                     refresh_token='rt-old')
        with self.captureOnCommitCallbacks(execute=True):
            self.assertIn('accessToken', self.apple('new').json())
        self.assertEqual(SocialAccount.objects.get().refresh_token, 'rt-new')
        self.assertEqual(self.revoked(), ['rt-old'])

    def test_unlink_and_purge_revoke(self):
        member = self.make_member(self.phone)
        SocialAccount.objects.create(member=member, provider='apple', subject='a-1', client_id='kg.baytur.app',
                                     refresh_token='rt-1')
        self.auth(member)
        with self.captureOnCommitCallbacks(execute=True):
            self.api.delete('/api/v1/me/social/apple')
        self.assertEqual(self.revoked(), ['rt-1'])
        SocialAccount.objects.create(member=member, provider='apple', subject='a-2', client_id='kg.baytur.app',
                                     refresh_token='rt-2')
        with self.captureOnCommitCallbacks(execute=True):
            services.purge(member)
        self.assertEqual(self.revoked(), ['rt-1', 'rt-2'])
        self.assertFalse(SocialAccount.objects.exists())

    @override_settings(APPLE_PRIVATE_KEY_FILE='/secrets/missing.p8')
    def test_without_key_login_still_works(self):
        self.assertTrue(self.apple().json()['needPhone'])
        self.assertEqual(self.posts, [])
