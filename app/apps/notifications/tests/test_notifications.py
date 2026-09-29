from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.common.testing import BaseAPITestCase
from apps.notifications import services
from apps.notifications.models import Campaign, CampaignStatus, Notification

TZ = ZoneInfo('Asia/Bishkek')


class NotificationTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(marketing_consent=True, notify_promos=True)

    def test_quiet_hours_delay_everything_but_points(self):
        night = datetime(2026, 9, 28, 23, 30, tzinfo=TZ)
        with mock.patch('django.utils.timezone.now', return_value=night):
            promo = services.notify(self.member, 'campaign', 'A', 'B', promo=True)
            credited = services.notify(self.member, 'request.credited', 'A', 'B')
        self.assertEqual(promo.push_after, datetime(2026, 9, 29, 9, 0, tzinfo=TZ))
        self.assertIsNone(credited.push_after)

    def test_promo_monthly_limit_and_consent(self):
        no_consent = self.make_member(phone='+996555000077', marketing_consent=False, notify_promos=True)
        c = Campaign.objects.create(title={'ru': 'Акция'}, body={'ru': 'Текст'}, status=CampaignStatus.DRAFT)
        for _ in range(4):
            Notification.objects.create(member=self.member, kind='campaign', title='x', body='y', is_promo=True)
        services.send_campaign(c.pk)
        c.refresh_from_db()
        self.assertEqual(c.stats['sent'], 0)
        self.assertEqual(c.stats['skipped'], 1)
        self.assertFalse(Notification.objects.filter(member=no_consent).exists())

    def test_feed_and_read(self):
        self.auth(self.member)
        services.notify(self.member, 'request.credited', 'Кешбек', '+100')
        services.notify(self.member, 'request.rejected', 'Отказ', '...')
        d = self.api.get('/api/v1/me/notifications').json()
        self.assertEqual((len(d['items']), d['unread']), (2, 2))
        self.api.post('/api/v1/me/notifications/read', {'id': d['items'][0]['id']}, format='json')
        self.assertEqual(self.api.post('/api/v1/me/notifications/read', {'all': True}, format='json').json(),
                         {'unread': 0})

    def test_retention(self):
        n = services.notify(self.member, 'request.credited', 'A', 'B')
        Notification.objects.filter(pk=n.pk).update(created_at=timezone.now() - timedelta(days=31))
        self.assertEqual(services.purge_old_notifications(), 1)

    def test_template_rendering(self):
        title, body = services.render('request.credited', 'en', points=49000, item='Cedar barrel')
        self.assertEqual(body, '+49 000 points for “Cedar barrel”')


class ExpiryTests(BaseAPITestCase):
    def test_points_expire_after_12_months_tier_kept(self):
        from apps.loyalty.models import Wallet
        from apps.loyalty.services import expire_inactive_wallets, warn_expiring_points
        m = self.make_member(points=300_000)
        Wallet.objects.filter(member=m).update(last_activity_at=timezone.now() - timedelta(days=360), tier='silver')
        self.assertEqual(warn_expiring_points(), 1)
        self.assertEqual(warn_expiring_points(), 0)      # однократно на порог
        Wallet.objects.filter(member=m).update(last_activity_at=timezone.now() - timedelta(days=370))
        self.assertEqual(expire_inactive_wallets(), 1)
        w = Wallet.objects.get(member=m)
        self.assertEqual((w.balance, w.tier_id), (0, 'silver'))
        self.assertTrue(m.operations.filter(kind='expire', points=-300_000).exists())
