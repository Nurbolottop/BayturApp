from unittest import mock

from django.core.cache import cache

from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Operation, OperationKind, WelcomeBonusGrant
from apps.members.models import Member, OtpChallenge
from apps.members.services import purge
from apps.notifications.models import Notification

A = '/api/v1/auth'
PHONE = '+996555333444'


def last_code(phone):
    return cache.get(f'sms:last:{phone}').rsplit(' ', 1)[-1]


class WelcomeBonusTests(BaseAPITestCase):
    def register(self, phone=PHONE):
        self.api.post(f'{A}/otp/request', {'phone': phone}, format='json')
        token = self.api.post(f'{A}/otp/verify', {'phone': phone, 'code': last_code(phone)},
                              format='json').json()['registrationToken']
        with self.captureOnCommitCallbacks(execute=True):
            r = self.api.post(f'{A}/register', {'registrationToken': token, 'firstName': 'Айгуль', 'lastName': 'Асанова',
                                               'birthday': '1995-03-01', 'acceptTerms': True}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return Member.objects.get(phone=phone)

    def test_off_by_default(self):
        member = self.register()
        self.assertEqual(self.wallet(member).balance, 0)
        self.assertFalse(WelcomeBonusGrant.objects.exists())

    def test_points_to_balance_only(self):
        self.settings_obj(welcome_bonus_points=500)
        member = self.register()
        w = self.wallet(member)
        self.assertEqual((w.balance, w.current, w.lifetime), (500, 0, 0))
        op = Operation.objects.get(member=member, kind=OperationKind.WELCOME)
        self.assertEqual(op.points, 500)
        self.assertTrue(Notification.objects.filter(member=member, kind='welcome.bonus').exists())
        self.auth(member)
        history = self.api.get('/api/v1/wallet/operations').json()['items']
        self.assertEqual([(o['kind'], o['points']) for o in history], [('welcome', 500)])

    def test_realtime_event(self):
        self.settings_obj(welcome_bonus_points=300)
        with mock.patch('apps.notifications.services.publish_member') as pub:
            self.register()
        self.assertIn(('welcome.bonus', {'points': 300}), [c.args[1:] for c in pub.call_args_list])

    def test_counts_for_tier(self):
        self.settings_obj(welcome_bonus_points=1000, welcome_bonus_counts_for_tier=True)
        w = self.wallet(self.register())
        self.assertEqual((w.balance, w.current, w.lifetime), (1000, 1000, 1000))

    def test_once_per_phone_even_after_deletion(self):
        self.settings_obj(welcome_bonus_points=500)
        member = self.register()
        purge(member)                                      # номер освобождается
        OtpChallenge.objects.all().delete()               # повторный SMS-код — без ожидания 60 с
        cache.clear()
        again = self.register()
        self.assertNotEqual(again.pk, member.pk)
        self.assertEqual(self.wallet(again).balance, 0)
        self.assertEqual(WelcomeBonusGrant.objects.count(), 1)
        self.assertFalse(WelcomeBonusGrant.objects.filter(phone_hash__contains=PHONE[1:]).exists())  # номер не хранится
