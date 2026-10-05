from datetime import timedelta
from unittest import mock

from django.utils import timezone

from apps.cashback import services
from apps.cashback.models import CashbackRequest, RequestStatus
from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Operation
from apps.loyalty.services import ledger_mismatches

URL = '/api/v1/cashback-requests'


class QuoteTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=845_000)
        self.auth(self.member)

    def test_quote_requires_login(self):
        self.api.credentials()
        r = self.api.post(f'{URL}/quote', {'itemId': 'spa-bochka', 'quantity': 2}, format='json')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()['error']['code'], 'auth_required')

    def test_quote_spec_example(self):
        r = self.api.post(f'{URL}/quote', {'itemId': 'spa-bochka', 'quantity': 2, 'pointsSom': 1500, 'method': 'finik'},
                          format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((d['total'], d['pointsSom'], d['points'], d['moneySom'], d['cashback']),
                         (5000, 1500, 150_000, 3500, 49_000))
        self.assertEqual(d['maxPointsSom'], 5000)
        self.assertEqual(d['availablePoints'], 845_000)
        self.assertEqual(d['bonuses'][0]['kind'], 'promo')

    def test_quote_clamps_slider(self):
        r = self.api.post(f'{URL}/quote', {'itemId': 'room-deluxe', 'quantity': 3, 'pointsSom': 999_999}, format='json')
        d = r.json()
        self.assertEqual(d['maxPointsSom'], 8450)       # min(69 000 × 0.3 = 20 700, 845 000 / 100)
        self.assertEqual(d['pointsSom'], 8450)

    def test_quote_check_amount_range(self):
        r = self.api.post(f'{URL}/quote', {'itemId': 'food-davinci', 'checkAmount': 100}, format='json')
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()['error']['code'], 'amount_out_of_range')

    def test_birthday_doubles_rate(self):
        today = timezone.localdate()
        self.member.birthday = today.replace(year=1990)
        self.member.save()
        r = self.api.post(f'{URL}/quote', {'itemId': 'spa-stone', 'quantity': 1}, format='json')
        d = r.json()
        self.assertEqual(d['cashback'], 3500 * 14)  # 0.07 × 2
        self.assertEqual(d['bonuses'][0]['kind'], 'birthday')

    def test_promo_and_birthday_take_max_not_product(self):
        today = timezone.localdate()
        self.member.birthday = today.replace(year=1990)
        self.member.save()
        # бочка: promo 0.14, ДР 0.07×2 = 0.14 → 0.14, не 0.28
        r = self.api.post(f'{URL}/quote', {'itemId': 'spa-bochka', 'quantity': 1}, format='json')
        self.assertEqual(r.json()['cashback'], 2500 * 14)


class CreateRequestTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=845_000)
        self.auth(self.member)

    def create(self, key=None, **data):
        headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
        return self.api.post(URL, data, format='json', **headers)

    def test_create_cash_request_reserves_points(self):
        r = self.create(itemId='spa-stone', quantity=2, pointsSom=1000, method='cash')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(d['status'], 'pending')
        self.assertEqual(d['split'], {'total': 7000, 'pointsSom': 1000, 'points': 100_000, 'moneySom': 6000,
                                      'rate': 0.07, 'cashback': 42_000})
        self.assertIn('pending', d['timeline'])
        self.assertTrue(d['createdAt'].endswith('+06:00'))
        w = self.wallet(self.member)
        self.assertEqual((w.balance, w.reserved, w.available), (845_000, 100_000, 745_000))
        wallet = self.api.get('/api/v1/wallet').json()
        self.assertEqual(wallet['pendingCashback'], 42_000)

    def test_client_cannot_inject_split(self):
        r = self.create(itemId='spa-stone', quantity=1, pointsSom=0, method='cash',
                        split={'cashback': 99_999_999}, rules={'rate': 1})
        self.assertEqual(r.json()['split']['cashback'], 24_500)

    def test_idempotency_key(self):
        r1 = self.create('key-1', itemId='spa-stone', quantity=1, pointsSom=500, method='cash')
        r2 = self.create('key-1', itemId='spa-stone', quantity=1, pointsSom=500, method='cash')
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()['id'], r2.json()['id'])
        self.assertEqual(CashbackRequest.objects.count(), 1)
        self.assertEqual(self.wallet(self.member).reserved, 50_000)

    def test_errors(self):
        cases = [
            (dict(itemId='spa-stone', quantity=1, pointsSom=9000, method='cash'), 422, 'points_limit_exceeded'),
            (dict(itemId='room-deluxe', quantity=1, pointsSom=7000, method='cash'), 422, 'points_limit_exceeded'),
            (dict(itemId='pools-thermal', quantity=1, method='freedomPay'), 422, 'method_not_allowed'),
            (dict(itemId='spa-stone', quantity=11, method='cash'), 422, 'amount_out_of_range'),
            (dict(itemId='nope', quantity=1, method='cash'), 404, 'item_not_found'),
            (dict(itemId='spa-stone', quantity=1, method='finik'), 422, 'payment_invalid'),
            (dict(itemId='spa-stone', quantity=1), 422, 'method_not_allowed'),
        ]
        for data, status, code in cases:
            r = self.create(**data)
            self.assertEqual((r.status_code, r.json()['error']['code']), (status, code), data)

    def test_insufficient_points(self):
        poor = self.make_member(phone='+996555000002', points=10_000)
        self.auth(poor)
        r = self.create(itemId='spa-stone', quantity=1, pointsSom=500, method='cash')
        self.assertEqual(r.json()['error']['code'], 'insufficient_points')

    def test_all_points_payment_has_no_method(self):
        r = self.create(itemId='spa-stone', quantity=1, pointsSom=3500, method='cash')
        d = r.json()
        self.assertIsNone(d['method'])
        self.assertEqual(d['split']['cashback'], 0)

    def test_inactive_item_rejected_but_readable_for_history(self):
        from apps.catalog.models import Item
        Item.objects.filter(pk='spa-hammam').update(is_active=False)
        self.assertEqual(self.create(itemId='spa-hammam', quantity=1, method='cash').status_code, 404)
        r = self.api.get('/api/v1/catalog/items/spa-hammam')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['isActive'])

    def test_rules_snapshot_survives_promo_change(self):
        r = self.create(itemId='spa-bochka', quantity=1, method='cash')
        from apps.catalog.models import ItemPromo
        ItemPromo.objects.all().delete()
        req = CashbackRequest.objects.get(pk=r.json()['id'])
        services.confirm_request(req.pk)
        services.credit_request(req.pk)
        self.assertEqual(Operation.objects.get(request=req, kind='cashback').points, 2500 * 14)

    def test_frozen_member_cannot_create(self):
        self.member.status = 'deactivated'
        self.member.save()
        from apps.members.models import MemberStatus
        self.assertEqual(self.member.status, MemberStatus.DEACTIVATED)
        with self.assertRaises(Exception):
            services.create_request(self.member, {'itemId': 'spa-stone', 'quantity': 1, 'method': 'cash'})


class LifecycleTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=190_000)
        self.auth(self.member)

    def new(self, item='spa-stone', qty=2, pts=1000, method='cash'):
        req, _ = services.create_request(self.member, {'itemId': item, 'quantity': qty, 'pointsSom': pts,
                                                       'method': method})
        return req

    def test_confirm_then_credit(self):
        req = self.new()
        services.confirm_request(req.pk)
        w = self.wallet(self.member)
        self.assertEqual((w.balance, w.reserved), (90_000, 0))
        spend = Operation.objects.get(request=req, kind='spend')
        self.assertEqual(spend.points, -100_000)
        with self.captureOnCommitCallbacks(execute=True):
            services.credit_request(req.pk)
        w = self.wallet(self.member)
        self.assertEqual(w.balance, 90_000 + 42_000)
        self.assertEqual(w.lifetime, 42_000)             # lifetime растёт только на кешбек
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.CREDITED)
        self.assertEqual(set(req.timeline), {'pending', 'confirmed', 'credited'})
        self.assertEqual(ledger_mismatches(), [])
        self.assertTrue(self.member.notifications.filter(kind='request.credited').exists())

    def test_tier_upgrade_and_never_down(self):
        req = self.new(item='room-deluxe', qty=3, pts=0)   # кешбек 483 000 → Серебро («Нынешние» ≥ 200 000)
        services.confirm_request(req.pk)
        with self.captureOnCommitCallbacks(execute=True):
            services.credit_request(req.pk)
        w = self.wallet(self.member)
        self.assertEqual(w.tier_id, 'silver')
        # излишек сверх порога для «Нынешних» сгорает, «Доступные» и «За всё время» — полностью
        self.assertEqual((w.current, w.lifetime), (0, 483_000))
        # траты не понижают уровень
        spend = self.new(item='spa-stone', qty=1, pts=3500)
        services.confirm_request(spend.pk)
        self.assertEqual(self.wallet(self.member).tier_id, 'silver')
        self.assertTrue(self.member.notifications.filter(kind='tier.upgraded').exists())

    def test_cancel_only_pending(self):
        req = self.new()
        r = self.api.post(f'{URL}/{req.pk}/cancel')
        self.assertEqual(r.json()['status'], 'cancelled')
        self.assertEqual(self.wallet(self.member).reserved, 0)
        req2 = self.new()
        services.confirm_request(req2.pk)
        r = self.api.post(f'{URL}/{req2.pk}/cancel')
        self.assertEqual((r.status_code, r.json()['error']['code']), (409, 'invalid_status'))

    def test_other_member_request_is_404(self):
        req = self.new()
        other = self.make_member(phone='+996555000009')
        self.auth(other)
        self.assertEqual(self.api.get(f'{URL}/{req.pk}').status_code, 404)
        self.assertEqual(self.api.post(f'{URL}/{req.pk}/cancel').status_code, 404)

    def test_reject_releases_reserve_and_shows_reason(self):
        req = self.new()
        with self.captureOnCommitCallbacks(execute=True):
            services.reject_request(req.pk, code='wrong_amount', comment='чек на 5 000')
        self.assertEqual(self.wallet(self.member).reserved, 0)
        d = self.api.get(f'{URL}/{req.pk}').json()
        self.assertEqual(d['status'], 'rejected')
        self.assertIn('чек на 5 000', d['rejectReason'])

    def test_adjust_clamps_points_and_keeps_original_total(self):
        req = self.new(qty=2, pts=1000)                   # 7 000, баллами 1 000
        services.adjust_request(req.pk, 500)              # новая сумма меньше баллов
        req.refresh_from_db()
        self.assertEqual((req.total, req.points_som, req.money_som, req.original_total), (500, 500, 0, 7000))
        self.assertEqual(self.wallet(self.member).reserved, 50_000)
        services.adjust_request(req.pk, 9000)
        req.refresh_from_db()
        self.assertEqual(req.original_total, 7000)        # запоминается один раз
        self.assertEqual(req.points_som, 1000)            # запрошенное клиентом восстанавливается
        self.assertEqual(req.cashback, 8000 * 7)

    def test_active_filter_and_pagination(self):
        for _ in range(3):
            self.new(qty=1, pts=0)
        done = self.new(qty=1, pts=0)
        services.reject_request(done.pk)
        r = self.api.get(f'{URL}?status=active').json()
        self.assertEqual(len(r['items']), 3)
        page1 = self.api.get(f'{URL}?limit=2').json()
        self.assertEqual(len(page1['items']), 2)
        page2 = self.api.get(f'{URL}?limit=2&cursor={page1["nextCursor"]}').json()
        self.assertEqual(len(page2['items']), 2)
        self.assertIsNone(page2['nextCursor'])
        ids = [i['id'] for i in page1['items'] + page2['items']]
        self.assertEqual(len(set(ids)), 4)


class BackgroundTests(BaseAPITestCase):
    def test_auto_confirm_credit_and_expire(self):
        self.settings_obj(auto_confirm=True, confirm_delay_ms=0, credit_delay_ms=60_000, pending_ttl_hours=1)
        m = self.make_member(points=0)
        online_like, _ = services.create_request(m, {'itemId': 'spa-stone', 'quantity': 1, 'method': 'cash'})
        # наличные без auto_confirm_cash не подтверждаются сами
        self.assertIsNone(online_like.auto_confirm_at)
        points_only_member = self.make_member(phone='+996555000003', points=500_000)
        req, _ = services.create_request(points_only_member, {'itemId': 'spa-stone', 'quantity': 1, 'pointsSom': 3500})
        self.assertIsNotNone(req.auto_confirm_at)
        services.process_due(timezone.now() + timedelta(seconds=1))
        req.refresh_from_db()
        self.assertEqual(req.status, 'confirmed')
        services.process_due(timezone.now() + timedelta(seconds=61))
        req.refresh_from_db()
        self.assertEqual(req.status, 'credited')
        # истёк срок pending → автоотказ и возврат резерва
        services.process_due(timezone.now() + timedelta(hours=2))
        online_like.refresh_from_db()
        self.assertEqual((online_like.status, online_like.reject_code), ('rejected', 'expired'))

    def test_test_account_is_auto_confirmed(self):
        m = self.make_member(points=0, is_test=True)
        req, _ = services.create_request(m, {'itemId': 'spa-stone', 'quantity': 1, 'method': 'cash'})
        self.assertIsNotNone(req.auto_confirm_at)

    def test_parallel_requests_cannot_overspend(self):
        """Две заявки на весь баланс: вторая упирается в резерв первой."""
        m = self.make_member(points=350_000)
        services.create_request(m, {'itemId': 'spa-stone', 'quantity': 1, 'pointsSom': 3500})
        with self.assertRaises(Exception) as e:
            services.create_request(m, {'itemId': 'spa-stone', 'quantity': 1, 'pointsSom': 3500})
        self.assertEqual(e.exception.code, 'insufficient_points')

    @mock.patch('apps.cashback.services._enqueue')
    def test_confirm_enqueues_credit(self, enqueue):
        m = self.make_member(points=0)
        req, _ = services.create_request(m, {'itemId': 'spa-stone', 'quantity': 1, 'method': 'cash'})
        with self.captureOnCommitCallbacks(execute=True):
            services.confirm_request(req.pk)
        self.assertTrue(enqueue.called)
