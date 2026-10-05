from unittest import mock
from xml.etree import ElementTree

import requests
from django.test import override_settings

from apps.common.testing import BaseAPITestCase
from apps.members.models import OtpChallenge

A = '/api/v1/auth'


def nikita_response(status, smscnt=1):
    body = (f'<?xml version="1.0" encoding="UTF-8"?><response><id>x</id><status>{status}</status>'
            f'<phones>1</phones><smscnt>{smscnt}</smscnt><message></message></response>')
    resp = mock.Mock(status_code=200, content=body.encode())
    resp.raise_for_status = mock.Mock()
    return resp


@override_settings(SMS_BACKEND='nikita', NIKITA_LOGIN='baytur', NIKITA_PASSWORD='p<&>ss', NIKITA_SENDER='BAYTUR',
                   NIKITA_TEST=False, OTP_FIXED_CODE='1234')
class NikitaSmsTests(BaseAPITestCase):
    phone = '+996555222333'

    def request_code(self):
        return self.api.post(f'{A}/otp/request', {'phone': self.phone}, format='json')

    def test_sends_xml_and_code_works(self):
        with mock.patch('apps.members.sms.requests.post', return_value=nikita_response(0)) as post:
            r = self.request_code()
        self.assertEqual(r.status_code, 200, r.content)
        url, kwargs = post.call_args[0][0], post.call_args[1]
        self.assertEqual(url, 'https://smspro.nikita.kg/api/message')
        xml = ElementTree.fromstring(kwargs['data'])
        self.assertEqual(xml.findtext('login'), 'baytur')
        self.assertEqual(xml.findtext('pwd'), 'p<&>ss')  # спецсимволы экранированы и читаются обратно
        self.assertEqual(xml.findtext('sender'), 'BAYTUR')
        self.assertEqual(xml.findtext('phones/phone'), '996555222333')
        self.assertRegex(xml.findtext('id'), r'^[0-9a-f]{12}$')
        self.assertIsNone(xml.find('test'))
        text = xml.findtext('text')
        self.assertRegex(text, r'^BAYTUR: код входа \d{4,6}$')
        # при реальной отправке фиксированный код 1234 не используется — в SMS настоящий
        code = text.rsplit(' ', 1)[-1]
        self.assertNotEqual(code, '1234')
        r = self.api.post(f'{A}/otp/verify', {'phone': self.phone, 'code': code}, format='json')
        self.assertTrue(r.json()['isNew'])

    def test_rejected_sms_keeps_retry_available(self):
        with mock.patch('apps.members.sms.requests.post', return_value=nikita_response(4)):
            r = self.request_code()
        self.assertEqual((r.status_code, r.json()['error']['code']), (503, 'sms_unavailable'))
        self.assertFalse(OtpChallenge.objects.exists())
        # повтор сразу, без ожидания retryIn
        with mock.patch('apps.members.sms.requests.post', return_value=nikita_response(0)):
            self.assertEqual(self.request_code().status_code, 200)

    def test_network_error(self):
        with mock.patch('apps.members.sms.requests.post', side_effect=requests.ConnectionError('down')):
            r = self.request_code()
        self.assertEqual(r.json()['error']['code'], 'sms_unavailable')

    def test_gateway_busy_retries_once_with_same_id(self):
        with mock.patch('apps.members.sms.requests.post', side_effect=[nikita_response(9), nikita_response(0)]) as post, \
                mock.patch('apps.members.sms.time.sleep') as sleep:
            self.assertEqual(self.request_code().status_code, 200)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(5)
        ids = [ElementTree.fromstring(c[1]['data']).findtext('id') for c in post.call_args_list]
        self.assertEqual(ids[0], ids[1])

    @override_settings(NIKITA_TEST=True)
    def test_test_mode(self):
        with mock.patch('apps.members.sms.requests.post', return_value=nikita_response(11)) as post:
            self.assertEqual(self.request_code().status_code, 200)
        self.assertEqual(ElementTree.fromstring(post.call_args[1]['data']).findtext('test'), '1')

    def test_store_test_phone_never_hits_provider(self):
        from apps.common.models import ProgramSettings
        ps = ProgramSettings.get()
        ps.test_enabled, ps.test_phone, ps.test_code = True, self.phone, '1234'
        ps.save()
        with mock.patch('apps.members.sms.requests.post') as post:
            self.assertEqual(self.request_code().status_code, 200)
        post.assert_not_called()
        r = self.api.post(f'{A}/otp/verify', {'phone': self.phone, 'code': '1234'}, format='json')
        self.assertTrue(r.json()['isNew'])

    def test_sms_check_command(self):
        from io import StringIO
        from django.core.management import call_command
        info = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response xmlns="http://Giper.mobi/schema/Info">'
                '<status>0</status><state>0</state><account>1500.00</account><smsprice>0.90</smsprice></response>')
        resp = mock.Mock(status_code=200, content=info.encode())
        resp.raise_for_status = mock.Mock()
        out = StringIO()
        with mock.patch('apps.members.sms.requests.post', return_value=resp) as post:
            call_command('sms_check', stdout=out)
        self.assertEqual(post.call_args[0][0], 'https://smspro.nikita.kg/api/info')
        self.assertIn('баланс 1500.00', out.getvalue())
        self.assertIn('активен', out.getvalue())


@override_settings(SMS_BACKEND='nikita', NIKITA_LOGIN='baytur', NIKITA_PASSWORD='x', NIKITA_SENDER='SMSPRO.KG',
                   NIKITA_TEST=False, OTP_FIXED_CODE='1234', SMS_ONLY_PHONES=['+996558000350'])
class SmsOnlyPhonesTests(BaseAPITestCase):
    """Тестовый режим провайдера: настоящая SMS — только номерам из списка, остальным — фиксированный код."""

    def test_listed_phone_gets_real_sms_with_random_code(self):
        with mock.patch('apps.members.sms.requests.post', return_value=nikita_response(0)) as post:
            r = self.api.post(f'{A}/otp/request', {'phone': '+996558000350'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        post.assert_called_once()
        code = ElementTree.fromstring(post.call_args[1]['data']).findtext('text').rsplit(' ', 1)[-1]
        self.assertNotEqual(code, '1234')
        r = self.api.post(f'{A}/otp/verify', {'phone': '+996558000350', 'code': '1234'}, format='json')
        self.assertEqual(r.json()['error']['code'], 'otp_invalid')
        r = self.api.post(f'{A}/otp/verify', {'phone': '+996558000350', 'code': code}, format='json')
        self.assertTrue(r.json()['isNew'])

    def test_other_phones_keep_fixed_code_without_sms(self):
        with mock.patch('apps.members.sms.requests.post') as post:
            r = self.api.post(f'{A}/otp/request', {'phone': '+996555000777'}, format='json')
        self.assertEqual(r.status_code, 200)
        post.assert_not_called()
        r = self.api.post(f'{A}/otp/verify', {'phone': '+996555000777', 'code': '1234'}, format='json')
        self.assertTrue(r.json()['isNew'])
