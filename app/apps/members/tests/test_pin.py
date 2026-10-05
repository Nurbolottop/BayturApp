from django.core.cache import cache
from django.test import override_settings

from apps.common.testing import BaseAPITestCase
from apps.members import services
from apps.members.models import MemberRefreshToken, MemberStatus

A = '/api/v1/auth'


@override_settings(OTP_FIXED_CODE='')
class PinTests(BaseAPITestCase):
    phone = '+996555444333'

    def sms_code(self, phone=None):
        phone = phone or self.phone
        cache.clear()
        self.api.post(f'{A}/otp/request', {'phone': phone}, format='json')
        return cache.get(f'sms:last:{phone}').rsplit(' ', 1)[-1]

    def pin_login(self, pin, phone=None):
        return self.api.post(f'{A}/pin', {'phone': phone or self.phone, 'pin': pin}, format='json')

    def test_register_with_pin_then_login_by_pin(self):
        r = self.api.post(f'{A}/otp/verify', {'phone': self.phone, 'code': self.sms_code()}, format='json')
        r = self.api.post(f'{A}/register', {
            'registrationToken': r.json()['registrationToken'], 'firstName': 'А', 'lastName': 'Б',
            'birthday': '1995-03-02', 'acceptTerms': True, 'pin': '482915'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()['profile']['hasPin'])
        r = self.pin_login('482915')
        self.assertIn('accessToken', r.json())
        # ограничения на число ошибок нет: после множества неверных верный PIN по-прежнему работает
        for _ in range(10):
            self.assertEqual(self.pin_login('000001').json()['error']['code'], 'pin_invalid')
        self.assertIn('accessToken', self.pin_login('482915').json())

    def test_unknown_phone_and_no_pin(self):
        self.assertEqual(self.pin_login('482915').json()['error']['code'], 'pin_invalid')
        self.make_member(self.phone)
        self.assertEqual(self.pin_login('482915').json()['error']['code'], 'pin_not_set')

    def test_pin_validation(self):
        member = self.make_member(self.phone)
        self.auth(member)
        for pin, code in (('12345', 'pin_format'), ('12a456', 'pin_format'), ('111111', 'pin_weak'),
                          ('123456', 'pin_weak'), ('987654', 'pin_weak')):
            self.assertEqual(self.api.post('/api/v1/me/pin', {'pin': pin}, format='json').json()['error']['code'],
                             code, pin)

    def test_set_and_change_pin_in_profile(self):
        member = self.make_member(self.phone)
        self.auth(member)
        r = self.api.post('/api/v1/me/pin', {'pin': '482915'}, format='json')
        self.assertTrue(r.json()['hasPin'])
        # смена — только со старым PIN
        r = self.api.post('/api/v1/me/pin', {'pin': '730264'}, format='json')
        self.assertEqual(r.json()['error']['code'], 'pin_invalid')
        r = self.api.post('/api/v1/me/pin', {'pin': '730264', 'currentPin': '482915'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('accessToken', self.pin_login('730264').json())

    def test_forgot_pin_reset_by_sms_revokes_sessions(self):
        member = self.make_member(self.phone)
        services.set_pin(member, '482915')
        old = self.auth(member)
        # слабый PIN отклоняется до проверки кода — код не сгорает
        code = self.sms_code()
        r = self.api.post(f'{A}/pin/reset', {'phone': self.phone, 'code': code, 'pin': '000000'}, format='json')
        self.assertEqual(r.json()['error']['code'], 'pin_weak')
        r = self.api.post(f'{A}/pin/reset', {'phone': self.phone, 'code': code, 'pin': '730264'}, format='json')
        self.assertIn('accessToken', r.json())
        self.assertEqual(MemberRefreshToken.objects.filter(member=member, revoked_at__isnull=True).count(), 1)
        r = self.api.post(f'{A}/refresh', {'refreshToken': old['refreshToken']}, format='json')
        self.assertEqual(r.status_code, 401)
        self.assertIn('accessToken', self.pin_login('730264').json())
        self.assertEqual(self.pin_login('482915').json()['error']['code'], 'pin_invalid')

    def test_wrong_sms_code_on_reset(self):
        member = self.make_member(self.phone)
        services.set_pin(member, '482915')
        self.sms_code()
        r = self.api.post(f'{A}/pin/reset', {'phone': self.phone, 'code': '0000', 'pin': '730264'}, format='json')
        self.assertEqual(r.json()['error']['code'], 'otp_invalid')

    def test_blocked_and_deactivated(self):
        member = self.make_member(self.phone)
        services.set_pin(member, '482915')
        member.status = MemberStatus.DEACTIVATED
        member.save()
        self.assertTrue(self.pin_login('482915').json()['deactivated'])
        member.status = MemberStatus.BLOCKED
        member.save()
        self.assertEqual(self.pin_login('482915').status_code, 403)

    def test_purge_clears_pin(self):
        member = self.make_member(self.phone)
        services.set_pin(member, '482915')
        services.purge(member)
        member.refresh_from_db()
        self.assertEqual(member.pin_hash, '')
