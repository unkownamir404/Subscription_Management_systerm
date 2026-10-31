from decimal import Decimal
from django.test import TestCase
from apps.billing.services.tax import compute_tax, round_money


class TaxServiceTests(TestCase):
    def test_tax_rounding_33_33_at_18_percent(self):
        """DESIGN.md §5.3 / prompt requirement: tax rounding on 33.33 at 18% -> 6.00."""
        net = Decimal("33.33")
        rate = Decimal("18.00")
        # 33.33 * 18 / 100 = 5.9994 -> rounds up to 6.00
        tax = compute_tax(net, rate)
        self.assertEqual(tax, Decimal("6.00"))

    def test_round_money_half_up(self):
        cases = [
            (Decimal("10.005"), Decimal("10.01")),
            (Decimal("10.004"), Decimal("10.00")),
            (Decimal("10.0051"), Decimal("10.01")),
            (Decimal("0.00"), Decimal("0.00")),
            (Decimal("99.999"), Decimal("100.00")),
            (10.555, Decimal("10.56")),
            ("25.125", Decimal("25.13")),
        ]
        for val, expected in cases:
            with self.subTest(val=val):
                self.assertEqual(round_money(val), expected)

    def test_table_driven_compute_tax(self):
        cases = [
            ("Standard 18% on 100", Decimal("100.00"), Decimal("18.00"), Decimal("18.00")),
            ("Zero tax rate", Decimal("100.00"), Decimal("0.00"), Decimal("0.00")),
            ("5% tax on 55.55", Decimal("55.55"), Decimal("5.00"), Decimal("2.78")),  # 2.7775 -> 2.78
            ("12% tax on 83.33", Decimal("83.33"), Decimal("12.00"), Decimal("10.00")),  # 9.9996 -> 10.00
            ("28% tax on 19.99", Decimal("19.99"), Decimal("28.00"), Decimal("5.60")),  # 5.5972 -> 5.60
        ]
        for name, net, rate, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(compute_tax(net, rate), expected)
