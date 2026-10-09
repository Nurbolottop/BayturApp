from datetime import timedelta
from unittest import mock

from django.utils import timezone

from apps.cashback import services
from apps.cashback.models import CashbackRequest, RequestStatus
from apps.common.errors import ApiError
from apps.common.testing import BaseAPITestCase
from apps.loyalty.models import Operation
from apps.loyalty.services import ledger_mismatches

URL = '/api/v1/cashback-requests'


class QuoteTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=84_500)          # 8 450 сом (10 баллов = 1 сом)
        self.auth(self.member)

    def test_quote_requires_login(self):
        self.api.credentials()
        r = self.api.post(f'{URL}/quote', {'itemId': 'spa-bochka', 'quantity': 2}, format='json')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()['error']['code'], 'auth_required')

    def test_quote_spec_example(self):
        r = self.api.post(f'{URL}/quote', {'itemId': 'spa-bochka', 'quantity': 2, 'method': 'finik'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((d['total'], d['pointsSom'], d['points'], d['moneySom'], d['cashback']),
                         (5000, 0, 0, 5000, 700))          # акция 14 %
        self.assertEqual(d['maxPointsSom'], 5000)        # баллов хватает на всю сумму
        self.assertEqual(d['availablePoints'], 84_500)
        self.assertEqual(d['bonuses'][0]['kind'], 'promo')

    def test_quote_all_or_nothing(self):
        # номер целиком баллами — лимита доли категории больше нет
        from apps.catalog.models import Item
        Item.objects.filter(pk='room-standard').update(price=8000)   # 84 500 баллов = 8 450 сом
        d = self.api.post(f'{URL}/quote', {'itemId': 'room-standard', 'quantity': 1, 'pointsSom': 1}, format='json').json()
        self.assertEqual((d['pointsSom'], d['moneySom'], d['maxPointsSom'], d['cashback']), (8000, 0, 8000, 0))
        # баллов не хватает на всю сумму → только деньгами
        d = self.api.post(f'{URL}/quote', {'itemId': 'room-deluxe', 'quantity': 3, 'pointsSom': 999_999},
                          format='json').json()
        self.assertEqual((d['maxPointsSom'], d['pointsSom'], d['moneySom']), (0, 0, 69_000))

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
        self.assertEqual(d['cashback'], 350)  # 3 500 × 5 % × 2
        self.assertEqual(d['bonuses'][0]['kind'], 'birthday')

    def test_promo_and_birthday_take_max_not_product(self):
        today = timezone.localdate()
        self.member.birthday = today.replace(year=1990)
        self.member.save()
        # бочка: акция 14 %, ДР 5 % × 2 = 10 % → берётся большая ставка 14 %, не произведение
        r = self.api.post(f'{URL}/quote', {'itemId': 'spa-bochka', 'quantity': 1}, format='json')
        self.assertEqual(r.json()['cashback'], 350)


class CreateRequestTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member(points=84_500)          # 8 450 сом (10 баллов = 1 сом)
        self.auth(self.member)

    def create(self, key=None, **data):
        headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
        return self.api.post(URL, data, format='json', **headers)

    def test_create_cash_request(self):
        r = self.create(itemId='spa-stone', quantity=2, method='cash')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(d['status'], 'pending')
        self.assertEqual(d['split'], {'total': 7000, 'pointsSom': 0, 'points': 0, 'moneySom': 7000,
                                      'rate': 0.05, 'cashback': 350})
        self.assertIn('pending', d['timeline'])
        self.assertTrue(d['createdAt'].endswith('+06:00'))
        w = self.wallet(self.member)
        self.assertEqual((w.balance, w.reserved, w.available), (84_500, 0, 84_500))
        wallet = self.api.get('/api/v1/wallet').json()
        self.assertEqual(wallet['pendingCashback'], 350)

    def test_points_request_reserves_points(self):
        r = self.create(itemId='spa-stone', quantity=2, pointsSom=7000)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['split']['points'], 70_000)
        w = self.wallet(self.member)
        self.assertEqual((w.reserved, w.available), (70_000, 14_500))

    def test_client_cannot_inject_split(self):
        r = self.create(itemId='spa-stone', quantity=1, pointsSom=0, method='cash',
                        split={'cashback': 99_999_999}, rules={'rate': 1})
        self.assertEqual(r.json()['split']['cashback'], 175)

    def test_idempotency_key(self):
        r1 = self.create('key-1', itemId='spa-stone', quantity=1, pointsSom=3500)
        r2 = self.create('key-1', itemId='spa-stone', quantity=1, pointsSom=3500)
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()['id'], r2.json()['id'])
        self.assertEqual(CashbackRequest.objects.count(), 1)
        self.assertEqual(self.wallet(self.member).reserved, 35_000)

    def test_errors(self):
        cases = [
            (dict(itemId='spa-stone', quantity=1, pointsSom=500, method='cash'), 422, 'points_partial'),
            (dict(itemId='spa-stone', quantity=1, pointsSom=9000, method='cash'), 422, 'points_partial'),
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
        poor = self.make_member(phone='+996555000002', points=1_000)
        self.auth(poor)
        r = self.create(itemId='spa-stone', quantity=1, pointsSom=3500)
        self.assertEqual(r.json()['error']['code'], 'insufficient_points')
        self.assertEqual(r.json()['error']['shortSom'], 3400)

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
        self.assertEqual(Operation.objects.get(request=req, kind='cashback').points, 350)  # акция 14 % из снимка

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
        self.member = self.make_member(points=50_000)
        self.auth(self.member)

    def new(self, item='spa-stone', qty=2, pts=0, method='cash'):
        req, _ = services.create_request(self.member, {'itemId': item, 'quantity': qty, 'pointsSom': pts,
                                                       'method': method})
        return req

    def _price(self, item_id):
        from apps.catalog.models import Item
        return Item.objects.get(pk=item_id).price

    def test_confirm_then_credit(self):
        req = self.new()                                  # 7 000 деньгами → кешбек 350
        paid = self.new(item='pools-thermal', qty=1, pts=self._price('pools-thermal'))
        services.confirm_request(req.pk)
        services.confirm_request(paid.pk)
        spent = paid.points
        w = self.wallet(self.member)
        self.assertEqual((w.balance, w.reserved), (50_000 - spent, 0))
        spend = Operation.objects.get(request=paid, kind='spend')
        self.assertEqual(spend.points, -spent)
        with self.captureOnCommitCallbacks(execute=True):
            services.credit_request(req.pk)
        w = self.wallet(self.member)
        self.assertEqual(w.balance, 50_000 - spent + 350)
        self.assertEqual(w.lifetime, 350)                # lifetime растёт только на кешбек
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.CREDITED)
        self.assertEqual(set(req.timeline), {'pending', 'confirmed', 'credited'})
        self.assertEqual(ledger_mismatches(), [])
        self.assertTrue(self.member.notifications.filter(kind='request.credited').exists())

    def test_tier_upgrade_and_never_down(self):
        from apps.loyalty.engine import adjust
        adjust(self.member, 197_000, ['current'], 'накоплено за год')
        req = self.new(item='room-deluxe', qty=3, pts=0)   # 69 000 сом × 5 % = 3 450 → «Нынешние» ≥ 200 000
        services.confirm_request(req.pk)
        with self.captureOnCommitCallbacks(execute=True):
            services.credit_request(req.pk)
        w = self.wallet(self.member)
        self.assertEqual(w.tier_id, 'silver')
        # излишек сверх порога для «Нынешних» сгорает, «За всё время» — полностью
        self.assertEqual((w.current, w.lifetime), (0, 3_450))
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

    def test_adjust_money_request_and_keep_original_total(self):
        req = self.new(qty=2)                             # 7 000 деньгами
        services.adjust_request(req.pk, 500)
        services.adjust_request(req.pk, 9000)
        req.refresh_from_db()
        self.assertEqual((req.total, req.points_som, req.money_som), (9000, 0, 9000))
        self.assertEqual(req.original_total, 7000)        # запоминается один раз
        self.assertEqual(req.cashback, 450)              # 9 000 × 5 %

    def test_adjust_points_request_stays_all_points(self):
        price = self._price('pools-thermal')
        req = self.new(item='pools-thermal', qty=1, pts=price)
        services.adjust_request(req.pk, price - 100)      # меньше — лишние баллы возвращаются в доступные
        req.refresh_from_db()
        self.assertEqual((req.points_som, req.money_som, req.cashback), (price - 100, 0, 0))
        self.assertEqual(self.wallet(self.member).reserved, (price - 100) * 10)
        with self.assertRaises(ApiError) as e:            # больше баланса — правка отклоняется, заявка не меняется
            services.adjust_request(req.pk, 6000)
        self.assertEqual(e.exception.code, 'insufficient_points')
        req.refresh_from_db()
        self.assertEqual((req.total, req.points_som, req.money_som), (price - 100, price - 100, 0))

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
        points_only_member = self.make_member(phone='+996555000003', points=50_000)
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
        m = self.make_member(points=35_000)
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
