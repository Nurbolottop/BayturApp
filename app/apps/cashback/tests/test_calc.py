from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.cashback.calc import Rules, compute_split, in_birthday_window, round_half_up
from apps.common.errors import ApiError


def rules(rate='0.07', share='1.00', methods=('cash',), pps=100):
    return Rules(rate=Decimal(rate), base_rate=Decimal(rate), max_points_share=Decimal(share), methods=list(methods),
                 points_per_som=pps)


class SplitTests(SimpleTestCase):
    def test_money_payment_cashback(self):
        """Бочка × 2 = 5 000 сом деньгами, promoRate 0.14 → кешбек 70 000."""
        s = compute_split(5000, rules('0.14'), available=845_000, requested_points_som=0)
        self.assertEqual((s.total, s.points_som, s.points, s.money_som, s.cashback), (5000, 0, 0, 5000, 70_000))
        self.assertEqual(s.max_points_som, 5000)

    def test_all_or_nothing(self):
        # хватает баллов на всю сумму → баллами целиком, любая категория (лимита доли нет)
        s = compute_split(69_000, rules('0.07', '0.30'), available=6_900_000, requested_points_som=1)
        self.assertEqual((s.points_som, s.money_som, s.cashback), (69_000, 0, 0))
        # не хватает → quote отдаёт «только деньгами»
        s = compute_split(69_000, rules('0.07'), available=6_899_999, requested_points_som=69_000)
        self.assertEqual((s.max_points_som, s.points_som, s.money_som), (0, 0, 69_000))

    def test_available_not_multiple_of_100_is_floored(self):
        self.assertEqual(compute_split(123, rules(), available=12_345, requested_points_som=123).points, 12_300)
        self.assertEqual(compute_split(124, rules(), available=12_345, requested_points_som=124).points_som, 0)

    def test_strict_errors(self):
        for requested in (500, 20_000):
            with self.assertRaises(ApiError) as e:
                compute_split(10_000, rules(), available=10_000_000, requested_points_som=requested, strict=True)
            self.assertEqual(e.exception.code, 'points_partial')
        with self.assertRaises(ApiError) as e:
            compute_split(10_000, rules(), available=100_000, requested_points_som=10_000, strict=True)
        self.assertEqual((e.exception.code, e.exception.extra['shortSom']), ('insufficient_points', 9000))

    def test_negative_request_is_zero(self):
        self.assertEqual(compute_split(1000, rules(), 100_000, -50).points_som, 0)

    def test_round_half_up(self):
        self.assertEqual(round_half_up(Decimal('0.5')), 1)
        self.assertEqual(round_half_up(Decimal('2.5')), 3)
        # 335 × 0.07 × 100 = 2 345
        self.assertEqual(compute_split(335, rules('0.07'), 0, 0).cashback, 2345)


class BirthdayWindowTests(SimpleTestCase):
    def test_window(self):
        bd = date(1994, 5, 14)
        self.assertTrue(in_birthday_window(bd, date(2026, 5, 14), 3, 3))
        self.assertTrue(in_birthday_window(bd, date(2026, 5, 11), 3, 3))
        self.assertTrue(in_birthday_window(bd, date(2026, 5, 17), 3, 3))
        self.assertFalse(in_birthday_window(bd, date(2026, 5, 18), 3, 3))
        self.assertFalse(in_birthday_window(None, date(2026, 5, 14), 3, 3))

    def test_year_boundary_and_leap(self):
        self.assertTrue(in_birthday_window(date(1990, 1, 1), date(2026, 12, 30), 3, 3))
        self.assertTrue(in_birthday_window(date(1992, 2, 29), date(2027, 2, 28), 3, 3))
