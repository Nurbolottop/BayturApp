"""
Правила балловой системы — тест-кейсы ТЗ лояльности §7.1 (номера в именах тестов) и сквозной пример §1.3.
Пороги как в примере: Серебро 200 000, Золото 300 000, Платина 900 000, надбавка к лимиту 10 000 (сид).
"""
from contextlib import contextmanager
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.db import transaction

from apps.common.errors import ApiError
from apps.common.testing import BaseAPITestCase
from apps.loyalty import engine
from apps.loyalty.models import (Achievement, LoyaltySettings, Operation, PeriodResult, Tier, TierAchievement,
                                 TierLimit, Wallet)
from apps.loyalty.services import ledger_mismatches, tier_state

TZ = ZoneInfo('Asia/Bishkek')


def dt(y, m=1, d=1, h=12, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=TZ)


class LoyaltyCase(BaseAPITestCase):
    phone_seq = 0

    @contextmanager
    def clock(self, when):
        with mock.patch('django.utils.timezone.now', return_value=when):
            yield

    def member(self, joined=None):
        LoyaltyCase.phone_seq += 1
        with self.clock(joined or dt(2026, 3, 1)):
            return self.make_member(phone=f'+99670{LoyaltyCase.phone_seq:07d}')

    def w(self, m):
        return Wallet.objects.select_related('tier', 'max_reached').get(member=m)

    def earn(self, m, points, when, key=None):
        with self.clock(when), self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                wallet = engine.lock_wallet(m)
                op = engine.accrue(wallet, points, at=when, idempotency_key=key)
                engine.evaluate(wallet, when)
        return op

    def spend(self, m, points, when):
        with self.clock(when), transaction.atomic():
            wallet = engine.lock_wallet(m)
            engine.change_reserved(wallet, points, at=when)
            engine.spend_reserved(wallet, points, None, at=when)

    def close(self, m, when):
        with self.clock(when), self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                return engine.ensure_period(engine.lock_wallet(m), when)

    def limit(self, m, tier_id):
        row = TierLimit.objects.filter(member=m, tier_id=tier_id).first()
        return row.limit if row else None

    def counters(self, m):
        w = self.w(m)
        return w.lifetime, w.current, w.balance, w.tier_id

    def gold_with_limit(self):
        """Пример §1.3 до 1 января 2027: Золото получено в 2026, лимит 510 000, пол — Серебро."""
        m = self.member(dt(2026, 3, 1))
        self.earn(m, 200_000, dt(2026, 3, 10))
        self.spend(m, 100_000, dt(2026, 6, 1))
        self.earn(m, 300_000, dt(2026, 8, 12))
        self.earn(m, 500_000, dt(2026, 12, 10))
        self.close(m, dt(2027, 1, 1, 0, 0, 5))
        return m


class EarnSpendTests(LoyaltyCase):
    def test_01_earn_goes_to_all_three(self):
        m = self.member()
        self.earn(m, 50_000, dt(2026, 4, 1))
        self.assertEqual(self.counters(m), (50_000, 50_000, 50_000, 'bronze'))

    def test_02_spend_only_from_available(self):
        m = self.member()
        engine.adjust(m, 100_000, ['available'], 'старт')
        engine.adjust(m, 80_000, ['current'], 'старт')
        self.spend(m, 60_000, dt(2026, 4, 1))
        w = self.w(m)
        self.assertEqual((w.balance, w.current, w.lifetime), (40_000, 80_000, 0))

    def test_03_promotion_resets_current(self):
        m = self.member()
        self.earn(m, 190_000, dt(2026, 4, 1))
        self.earn(m, 30_000, dt(2026, 4, 2))
        self.assertEqual(self.counters(m), (220_000, 0, 220_000, 'silver'))
        self.assertTrue(m.notifications.filter(kind='tier.upgraded', data__tierId='silver',
                                               data__fromTierId='bronze').exists())
        self.assertEqual(m.tier_changes.filter(cause='promotion').count(), 1)

    def test_04_carry_over(self):
        ls = LoyaltySettings.get()
        ls.carry_over = True
        ls.save()
        m = self.member()
        self.earn(m, 190_000, dt(2026, 4, 1))
        self.earn(m, 30_000, dt(2026, 4, 2))
        self.assertEqual(self.counters(m), (220_000, 20_000, 220_000, 'silver'))

    def test_04b_carry_over_jumps_tiers(self):
        ls = LoyaltySettings.get()
        ls.carry_over = True
        ls.save()
        m = self.member()
        self.earn(m, 520_000, dt(2026, 4, 1))   # 200 000 на Серебро + 300 000 на Золото, 20 000 остаются
        self.assertEqual(self.counters(m)[1:], (20_000, 520_000, 'gold'))

    def test_22_cannot_spend_reserved(self):
        m = self.member()
        engine.adjust(m, 30_000, ['available'], 'старт')
        with transaction.atomic():
            engine.change_reserved(engine.lock_wallet(m), 20_000)
        with self.assertRaises(ApiError) as e, transaction.atomic():
            engine.change_reserved(engine.lock_wallet(m), 15_000)
        self.assertEqual(e.exception.code, 'insufficient_points')
        self.assertEqual(self.w(m).available, 10_000)

    def test_25_same_idempotency_key_one_entry(self):
        m = self.member()
        self.earn(m, 50_000, dt(2026, 4, 1), key='cashback:req_1')
        self.earn(m, 50_000, dt(2026, 4, 1), key='cashback:req_1')
        self.assertEqual(Operation.objects.filter(idempotency_key='cashback:req_1').count(), 1)
        self.assertEqual(self.counters(m), (50_000, 50_000, 50_000, 'bronze'))


class PeriodCloseTests(LoyaltyCase):
    def test_05_promoted_in_period_sets_first_limit(self):
        m = self.gold_with_limit()
        r = PeriodResult.objects.get(member=m, period_key='2026')
        self.assertEqual((r.result, r.checked, r.current, r.limit_after), ('promoted_in_period', False, 500_000,
                                                                            510_000))
        self.assertEqual(self.limit(m, 'gold'), 510_000)
        self.assertEqual(self.counters(m), (1_000_000, 0, 900_000, 'gold'))

    def test_06_drop_one_step_limit_kept(self):
        m = self.gold_with_limit()
        self.earn(m, 400_000, dt(2027, 12, 1))
        self.close(m, dt(2028, 1, 1, 0, 1))
        self.assertEqual(self.counters(m), (1_400_000, 0, 1_300_000, 'silver'))
        self.assertEqual(self.limit(m, 'gold'), 510_000)
        self.assertEqual(PeriodResult.objects.get(member=m, period_key='2027').result, 'dropped')
        self.assertTrue(m.notifications.filter(kind='tier.downgraded', data__tierId='silver').exists())
        self.assertEqual(tier_state(self.w(m))['floor'], 'silver')

    def test_07_retained_limit_grows(self):
        m = self.gold_with_limit()
        self.earn(m, 600_000, dt(2027, 12, 1))
        self.close(m, dt(2028, 1, 1, 0, 1))
        self.assertEqual(self.w(m).tier_id, 'gold')
        self.assertEqual(self.limit(m, 'gold'), 610_000)
        self.assertTrue(m.notifications.filter(kind='tier.retained').exists())

    def test_08_exactly_limit_is_retained(self):
        m = self.gold_with_limit()
        self.earn(m, 510_000, dt(2027, 12, 1))
        self.close(m, dt(2028, 1, 1, 0, 1))
        self.assertEqual(self.w(m).tier_id, 'gold')
        self.assertEqual(self.limit(m, 'gold'), 520_000)

    def test_09_10_11_floor_and_limit_only_grows(self):
        m = self.gold_with_limit()
        self.earn(m, 400_000, dt(2027, 12, 1))
        self.close(m, dt(2028, 1, 1, 0, 1))                       # → Серебро навсегда
        self.close(m, dt(2029, 1, 1, 0, 1))                       # 9: пол не проверяется
        self.assertEqual(self.w(m).tier_id, 'silver')
        self.assertEqual(PeriodResult.objects.get(member=m, period_key='2028').result, 'floor')
        self.earn(m, 300_000, dt(2029, 5, 1))                     # снова Золото
        self.earn(m, 300_000, dt(2029, 11, 1))
        self.close(m, dt(2030, 1, 1, 0, 1))                       # 10: 310 000 < 510 000 — лимит прежний
        self.assertEqual(PeriodResult.objects.get(member=m, period_key='2029').result, 'promoted_in_period')
        self.assertEqual((self.w(m).tier_id, self.limit(m, 'gold')), ('gold', 510_000))

    def test_11_limit_replaced_by_bigger(self):
        m = self.gold_with_limit()
        self.earn(m, 400_000, dt(2027, 12, 1))
        self.close(m, dt(2028, 1, 1, 0, 1))
        self.earn(m, 300_000, dt(2028, 5, 1))
        self.earn(m, 800_000, dt(2028, 12, 1))
        self.close(m, dt(2029, 1, 1, 0, 1))
        self.assertEqual(self.limit(m, 'gold'), 810_000)

    def platinum_since_2027(self):
        m = self.gold_with_limit()
        self.earn(m, 900_000, dt(2027, 6, 1))                     # Платина в 2027, пол — Золото
        self.close(m, dt(2028, 1, 1, 0, 1))
        self.assertEqual(self.limit(m, 'platinum'), 10_000)       # ничего не собрал после перехода → надбавка
        return m

    def test_12_13_platinum_drops_to_eternal_gold(self):
        m = self.platinum_since_2027()
        self.close(m, dt(2029, 1, 1, 0, 1))                       # 0 < 10 000 → Золото навсегда
        self.assertEqual(self.w(m).tier_id, 'gold')
        state = tier_state(self.w(m))
        self.assertEqual((state['floor'], state['isFloor'], state['retention']['reason']), ('gold', True, 'floor'))
        self.close(m, dt(2030, 1, 1, 0, 1))                       # 13: за год 0 — остаётся Золото
        self.assertEqual(self.w(m).tier_id, 'gold')
        self.assertEqual(PeriodResult.objects.get(member=m, period_key='2029').result, 'floor')

    def link(self, tier_id, ach_id, usage, scope='lifetime'):
        ach, _ = Achievement.objects.get_or_create(id=ach_id, defaults={
            'title': {'ru': ach_id}, 'type': 'manual', 'scope': scope})
        TierAchievement.objects.create(tier_id=tier_id, achievement=ach, usage=usage)
        return ach

    def test_14_15_titanium_waits_for_achievement(self):
        m = self.platinum_since_2027()
        ach = self.link('titanium', 'vip-evening', 'entry')
        self.earn(m, 2_500_000, dt(2028, 3, 1))
        self.assertEqual(self.counters(m)[1:], (2_500_000, 4_300_000, 'platinum'))
        self.assertEqual(tier_state(self.w(m))['next']['achievements'], {'required': 1, 'done': 0})
        with self.clock(dt(2028, 3, 2)), self.captureOnCommitCallbacks(execute=True):
            engine.grant_achievement(m, ach, reason='был на вечере')
        self.assertEqual(self.counters(m)[1:], (0, 4_300_000, 'titanium'))
        self.assertTrue(m.notifications.filter(kind='achievement.completed', data__achievementId='vip-evening',
                                               data__tierId='titanium').exists())
        self.assertTrue(m.notifications.filter(kind='tier.upgraded', data__tierId='titanium').exists())

    def titanium_since_2028(self):
        m = self.platinum_since_2027()
        self.earn(m, 2_000_000, dt(2028, 3, 1))                   # Титан без заданий на вход
        self.close(m, dt(2029, 1, 1, 0, 1))
        self.link('titanium', 'annual-evening', 'retention', scope='period')
        self.earn(m, 50_000, dt(2029, 6, 1))                      # лимит 10 000 собран
        return m

    def test_16_titanium_needs_retention_achievement(self):
        m = self.titanium_since_2028()
        self.close(m, dt(2030, 1, 1, 0, 1))
        self.assertEqual(self.w(m).tier_id, 'platinum')

    def test_16b_titanium_retained_with_achievement(self):
        m = self.titanium_since_2028()
        with self.clock(dt(2029, 7, 1)):
            engine.grant_achievement(m, Achievement.objects.get(pk='annual-evening'))
        self.close(m, dt(2030, 1, 1, 0, 1))
        self.assertEqual(self.w(m).tier_id, 'titanium')

    def test_17_titanium_can_be_floor(self):
        Tier.objects.filter(pk='titanium').update(can_be_floor=True)
        m = self.titanium_since_2028()
        self.assertEqual(tier_state(self.w(m))['floor'], 'platinum')   # пол — уровень ниже Титана
        self.close(m, dt(2030, 1, 1, 0, 1))
        self.assertEqual(self.w(m).tier_id, 'platinum')

    def test_18_boundary_credit_and_close(self):
        m = self.member(dt(2026, 3, 1))
        self.earn(m, 50_000, dt(2026, 12, 31, 23, 59, 59))
        self.close(m, dt(2027, 1, 1, 0, 0, 0))
        self.assertEqual(PeriodResult.objects.get(member=m, period_key='2026').current, 50_000)
        # начисление после полуночи, когда фоновое закрытие до клиента ещё не дошло
        m2 = self.member(dt(2026, 3, 1))
        self.earn(m2, 30_000, dt(2026, 12, 31, 23, 59, 59))
        self.earn(m2, 70_000, dt(2027, 1, 1, 0, 0, 1))
        self.assertEqual(PeriodResult.objects.get(member=m2, period_key='2026').current, 30_000)
        self.assertEqual(self.counters(m2), (100_000, 70_000, 100_000, 'bronze'))
        self.close(m2, dt(2027, 1, 1, 0, 5))
        self.assertEqual(PeriodResult.objects.filter(member=m2).count(), 1)
        self.assertEqual(ledger_mismatches(), [])

    def test_19_resume_after_failure(self):
        members = [self.gold_with_limit() for _ in range(3)]
        for m in members:
            self.earn(m, 600_000, dt(2027, 12, 1))
        self.close(members[0], dt(2028, 1, 1, 0, 1))              # «упало после первого»
        first_limit = self.limit(members[0], 'gold')
        with self.clock(dt(2028, 1, 1, 0, 10)), self.captureOnCommitCallbacks(execute=True):
            status = engine.close_due_periods(dt(2028, 1, 1, 0, 10))
            again = engine.close_due_periods(dt(2028, 1, 1, 0, 20))
        self.assertEqual((status['total'], status['errors'], again['total']), (2, 0, 0))
        self.assertEqual(self.limit(members[0], 'gold'), first_limit)
        for m in members:
            self.assertEqual(PeriodResult.objects.filter(member=m, period_key='2027').count(), 1)
            self.assertEqual(self.limit(m, 'gold'), 610_000)

    def test_24_raising_threshold_demotes_nobody(self):
        m = self.gold_with_limit()
        Tier.objects.filter(pk='gold').update(threshold=1_000_000)
        engine.recalc_promotions()
        self.assertEqual(self.w(m).tier_id, 'gold')

    def test_example_1_3_end_to_end(self):
        m = self.gold_with_limit()
        self.earn(m, 400_000, dt(2027, 12, 1))
        self.close(m, dt(2028, 1, 1, 0, 1))
        self.assertEqual(self.counters(m), (1_400_000, 0, 1_300_000, 'silver'))
        self.earn(m, 300_000, dt(2028, 5, 1))
        self.assertEqual(self.counters(m), (1_700_000, 0, 1_600_000, 'gold'))
        self.earn(m, 800_000, dt(2028, 12, 1))
        self.close(m, dt(2029, 1, 1, 0, 1))
        self.assertEqual(self.counters(m), (2_500_000, 0, 2_400_000, 'gold'))
        self.assertEqual(self.limit(m, 'gold'), 810_000)
        self.earn(m, 900_000, dt(2029, 9, 1))                     # 900 000 → Платина, Золото становится полом
        state = tier_state(self.w(m))
        self.assertEqual((state['id'], state['floor']), ('platinum', 'gold'))
        self.assertEqual(ledger_mismatches(), [])
        self.auth(m)
        data = self.api.get('/api/v1/me/loyalty/history').json()
        self.assertEqual([p['key'] for p in data['periods']], ['2028', '2027', '2026'])
        self.assertEqual([p['result'] for p in data['periods']], ['promoted_in_period', 'dropped',
                                                                  'promoted_in_period'])
        self.assertEqual(data['tierChanges'][0]['to'], 'platinum')


class CorrectionTests(LoyaltyCase):
    def credited_request(self, m):
        from apps.cashback import services as cs
        self.auth(m)
        req = cs.create_request(m, {'itemId': 'spa-stone', 'quantity': 1, 'pointsSom': 0, 'method': 'cash'})[0]
        cs.confirm_request(req.pk)
        with self.captureOnCommitCallbacks(execute=True):
            cs.credit_request(req.pk)
        req.refresh_from_db()
        return req

    def test_20_reversal_this_period(self):
        m = self.make_member(phone='+996700100001')
        req = self.credited_request(m)
        before = self.counters(m)
        self.assertEqual(before[:3], (req.cashback, req.cashback, req.cashback))
        engine.reverse_cashback(req, reason='отмена')
        self.assertEqual(self.counters(m), (0, 0, 0, before[3]))
        engine.reverse_cashback(req, reason='повтор')               # повтор — та же проводка
        self.assertEqual(Operation.objects.filter(request=req, kind='reversal').count(), 1)
        self.assertEqual(ledger_mismatches(), [])

    def test_21_reversal_of_previous_period_keeps_current(self):
        m = self.make_member(phone='+996700100002')
        req = self.credited_request(m)
        wallet = self.w(m)
        self.close(m, wallet.period_end)                           # период начисления закрыт
        engine.adjust(m, 7_000, ['current'], 'для проверки')
        engine.reverse_cashback(req)
        w = self.w(m)
        self.assertEqual((w.current, w.balance, w.lifetime), (7_000, 0, 0))

    def test_adjustment_counters_and_promotion(self):
        m = self.make_member(phone='+996700100003')
        with self.captureOnCommitCallbacks(execute=True):
            engine.adjust(m, 250_000, ['current', 'lifetime'], 'перенос из старой системы')
        self.assertEqual(self.counters(m), (250_000, 0, 0, 'silver'))
        with self.assertRaises(ApiError):
            engine.adjust(m, -1, ['available'], 'минус')
        with self.assertRaises(ApiError):
            engine.adjust(m, 10, [], 'без счётчиков')

    def test_set_tier_below_floor_needs_flag(self):
        m = self.make_member(phone='+996700100004')
        Wallet.objects.filter(member=m).update(tier='platinum', max_reached='platinum')
        with self.assertRaises(ApiError) as e:
            engine.set_tier(m, Tier.objects.get(pk='silver'), 'ошибка')
        self.assertEqual(e.exception.code, 'below_floor')
        engine.set_tier(m, Tier.objects.get(pk='silver'), 'по решению владельца', allow_below_floor=True)
        self.assertEqual(self.w(m).tier_id, 'silver')


class WalletApiTests(LoyaltyCase):
    def test_26_wallet_payload_new_and_old_fields(self):
        m = self.make_member(phone='+996700200001', points=5_000)
        engine.adjust(m, 150_000, ['current', 'lifetime'], 'тест')
        self.auth(m)
        data = self.api.get('/api/v1/wallet').json()
        for key in ('available', 'reserved', 'current', 'lifetime', 'pendingCashback', 'tier', 'period',
                    'balance', 'nextTier', 'leftToNext', 'progress'):
            self.assertIn(key, data)
        self.assertNotIn('expiresAt', data)
        self.assertEqual((data['available'], data['current'], data['lifetime']), (5_000, 150_000, 150_000))
        self.assertEqual((data['nextTier'], data['leftToNext'], data['progress']), ('silver', 50_000, 0.75))
        self.assertEqual(data['tier']['next'], {'id': 'silver', 'threshold': 200_000, 'left': 50_000,
                                                'progress': 0.75, 'achievements': {'required': 0, 'done': 0}})
        self.assertEqual(data['tier']['retention']['reason'], 'not_required')

    def test_retention_check_and_at_risk(self):
        m = self.gold_with_limit()
        self.earn(m, 100_000, dt(2027, 11, 1))
        self.auth(m)
        with self.clock(dt(2027, 12, 1)):
            data = self.api.get('/api/v1/wallet').json()
        r = data['tier']['retention']
        self.assertEqual((r['reason'], r['limit'], r['collected'], r['left'], r['atRisk'], r['dropTo']),
                         ('check', 510_000, 100_000, 410_000, True, 'silver'))
        self.assertEqual(data['period']['key'], '2027')
        self.assertEqual(r['periodEnd'], '2027-12-31T23:59:59+06:00')  # = 2027-12-31T17:59:59Z
        with self.clock(dt(2027, 12, 1)):
            self.assertEqual(engine.warn_at_risk(dt(2027, 12, 1)), 1)
            self.assertEqual(engine.warn_at_risk(dt(2027, 12, 2)), 0)   # однократно на порог
            self.assertEqual(engine.warn_at_risk(dt(2027, 12, 25)), 1)  # порог 7 дней

    def test_new_this_period_reason(self):
        m = self.member(dt(2026, 3, 1))
        self.earn(m, 200_000, dt(2026, 4, 1))
        self.auth(m)
        with self.clock(dt(2026, 5, 1)):
            r = self.api.get('/api/v1/wallet').json()['tier']['retention']
        self.assertEqual((r['required'], r['reason']), (False, 'new_this_period'))

    def test_operations_hide_service_entries(self):
        m = self.member(dt(2026, 3, 1))
        self.earn(m, 250_000, dt(2026, 4, 1))                       # + promotion_reset
        self.spend(m, 10_000, dt(2026, 4, 2))                       # reserve + spend
        self.auth(m)
        kinds = [o['kind'] for o in self.api.get('/api/v1/wallet/operations').json()['items']]
        self.assertEqual(kinds, ['spend', 'cashback'])

    def test_achievements_progress(self):
        Achievement.objects.create(id='rich', title={'ru': 'Накопить'}, type='lifetime_points',
                                   params={'points': 100_000})
        Achievement.objects.create(id='hidden', title={'ru': 'Скрытое'}, type='manual', visible=False)
        m = self.member()
        self.earn(m, 40_000, dt(2026, 4, 1))
        self.auth(m)
        items = self.api.get('/api/v1/me/achievements').json()['items']
        self.assertEqual(items, [{'id': 'rich', 'progress': 40_000, 'target': 100_000, 'completedAt': None,
                                  'periodKey': None}])
        self.earn(m, 70_000, dt(2026, 4, 2))
        item = self.api.get('/api/v1/me/achievements').json()['items'][0]
        self.assertIsNotNone(item['completedAt'])
        program = self.api.get('/api/v1/loyalty/program').json()
        self.assertEqual([a['id'] for a in program['achievements']], ['rich'])
        self.assertEqual(program['settings'], {'periodType': 'calendar_year', 'floorDepth': 1})
