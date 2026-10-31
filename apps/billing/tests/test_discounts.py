from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from django.db import connection
from django.test import TestCase, TransactionTestCase
from apps.accounts.models import Customer
from apps.billing.models import DiscountRedemption, Invoice
from apps.billing.services.discounts import find_best_discounts, redeem
from apps.catalog.models import Discount, DiscountKind, DiscountScope, Plan, Product, ProductType
from apps.subscriptions.models import Subscription, SubscriptionLine


class DiscountServiceTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name="Acme Corp")
        self.plan = Plan.objects.create(
            name="Pro Plan",
            price=Decimal("1000.00"),
            interval="monthly",
            valid_from=date(2026, 1, 1),
        )
        self.subscription = Subscription.objects.create(
            number="SUB-2026-000001",
            customer=self.customer,
            plan=self.plan,
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )
        self.product_a = Product.objects.create(
            name="Service Alpha",
            product_type=ProductType.SERVICE,
            sales_price=Decimal("500.00"),
        )
        self.product_b = Product.objects.create(
            name="Service Beta",
            product_type=ProductType.SERVICE,
            sales_price=Decimal("300.00"),
        )
        self.line1 = SubscriptionLine.objects.create(
            subscription=self.subscription,
            product=self.product_a,
            quantity=2,
            unit_price=Decimal("500.00"),  # subtotal = 1000.00
            tax_rate=Decimal("18.00"),
        )
        self.line2 = SubscriptionLine.objects.create(
            subscription=self.subscription,
            product=self.product_b,
            quantity=1,
            unit_price=Decimal("300.00"),  # subtotal = 300.00
            tax_rate=Decimal("18.00"),
        )

    def test_percent_and_fixed_discount_calculations(self):
        """Percent and fixed discounts applied correctly."""
        disc_pct = Discount.objects.create(
            name="10% Off Subscription",
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.SUBSCRIPTION,
        )

        res = find_best_discounts([self.line1, self.line2], on_date=date(2026, 6, 1))
        # Total subtotal = 1300.00 -> 10% = 130.00
        self.assertEqual(res.total_discount, Decimal("130.00"))
        self.assertEqual(res.subscription_discount, disc_pct)

    def test_fixed_discount_capped_at_line_amount(self):
        """Fixed discounts are capped at the amount they apply to."""
        large_fixed = Discount.objects.create(
            name="Massive Discount",
            kind=DiscountKind.FIXED,
            value=Decimal("2000.00"),  # exceeds subtotal 1000.00 on line1
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.PRODUCTS,
        )
        large_fixed.products.add(self.product_a)

        res = find_best_discounts([self.line1], on_date=date(2026, 6, 1))
        # Line 1 subtotal is 1000.00, fixed discount is 2000.00 -> capped at 1000.00
        self.assertEqual(res.line_allocations[0].product_discount_amount, Decimal("1000.00"))
        self.assertEqual(res.total_discount, Decimal("1000.00"))

    def test_min_amount_and_min_qty_boundaries(self):
        """Table-driven test for boundaries: just below, equal, above."""
        disc = Discount.objects.create(
            name="Threshold Discount",
            kind=DiscountKind.FIXED,
            value=Decimal("50.00"),
            min_amount=Decimal("1000.00"),
            min_qty=3,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.SUBSCRIPTION,
        )

        class DummyLine:
            def __init__(self, qty, price):
                self.quantity = qty
                self.unit_price = Decimal(str(price))
                self.product = None

        cases = [
            ("Below amount & below qty", [DummyLine(2, "400.00")], False),    # total=800, qty=2
            ("Equal amount & below qty", [DummyLine(2, "500.00")], False),    # total=1000, qty=2
            ("Below amount & equal qty", [DummyLine(3, "300.00")], False),    # total=900, qty=3
            ("Equal amount & equal qty", [DummyLine(3, "333.34")], True),     # total=1000.02 >= 1000, qty=3
            ("Above amount & above qty", [DummyLine(4, "300.00")], True),     # total=1200, qty=4
        ]

        for desc, lines, expected_eligible in cases:
            with self.subTest(scenario=desc):
                res = find_best_discounts(lines, on_date=date(2026, 6, 1))
                if expected_eligible:
                    self.assertEqual(res.subscription_discount, disc)
                    self.assertEqual(res.total_discount, Decimal("50.00"))
                else:
                    self.assertIsNone(res.subscription_discount)
                    self.assertEqual(res.total_discount, Decimal("0.00"))

    def test_start_and_end_date_edges(self):
        """Table-driven tests for date edges."""
        Discount.objects.create(
            name="Mid-Year Sale",
            kind=DiscountKind.PERCENT,
            value=Decimal("15.00"),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            scope=DiscountScope.SUBSCRIPTION,
        )

        cases = [
            ("Day before start date", date(2026, 5, 31), Decimal("0.00")),
            ("On start date", date(2026, 6, 1), Decimal("195.00")),   # 15% of 1300 = 195
            ("Midway through window", date(2026, 6, 15), Decimal("195.00")),
            ("On end date", date(2026, 6, 30), Decimal("195.00")),
            ("Day after end date", date(2026, 7, 1), Decimal("0.00")),
        ]

        for desc, check_date, expected_saving in cases:
            with self.subTest(scenario=desc):
                res = find_best_discounts([self.line1, self.line2], on_date=check_date)
                self.assertEqual(res.total_discount, expected_saving)

    def test_product_vs_subscription_scope_no_stacking_and_remainder(self):
        """
        No stacking: at most 1 product discount per line, at most 1 subscription discount per invoice.
        Subscription discount applies to remaining balance and is allocated with rounding remainder on last line.
        """
        p_disc = Discount.objects.create(
            name="10% off Product A",
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.PRODUCTS,
        )
        p_disc.products.add(self.product_a)

        s_disc = Discount.objects.create(
            name="100 INR off Total",
            kind=DiscountKind.FIXED,
            value=Decimal("100.00"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.SUBSCRIPTION,
        )

        # Line 1: subtotal 1000.00 -> Product discount = 100.00. Remaining net = 900.00.
        # Line 2: subtotal 300.00 -> Product discount = 0.00. Remaining net = 300.00.
        # Total remaining = 1200.00.
        # Subscription discount = 100.00 fixed.
        # Line 1 share: round_money(100.00 * 900 / 1200) = 75.00.
        # Line 2 share (remainder on last line): 100.00 - 75.00 = 25.00.
        res = find_best_discounts([self.line1, self.line2], on_date=date(2026, 6, 1))

        self.assertEqual(res.line_allocations[0].product_discount_amount, Decimal("100.00"))
        self.assertEqual(res.line_allocations[0].subscription_discount_amount, Decimal("75.00"))
        self.assertEqual(res.line_allocations[0].total_discount_amount, Decimal("175.00"))

        self.assertEqual(res.line_allocations[1].product_discount_amount, Decimal("0.00"))
        self.assertEqual(res.line_allocations[1].subscription_discount_amount, Decimal("25.00"))
        self.assertEqual(res.line_allocations[1].total_discount_amount, Decimal("25.00"))

        # Reconciles exactly to 100.00 + 100.00 = 200.00
        self.assertEqual(res.total_discount, Decimal("200.00"))

    def test_allocation_rounding_remainder_on_last_line(self):
        """Verify remainder is placed on the last line when fractions cannot be divided evenly."""
        s_disc = Discount.objects.create(
            name="10 INR off Total",
            kind=DiscountKind.FIXED,
            value=Decimal("10.00"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.SUBSCRIPTION,
        )

        class MockLine:
            def __init__(self, qty, price):
                self.quantity = qty
                self.unit_price = Decimal(str(price))
                self.product = None

        # 3 lines of equal 100.00 (total 300.00)
        lines = [MockLine(1, "100.00"), MockLine(1, "100.00"), MockLine(1, "100.00")]
        res = find_best_discounts(lines, on_date=date(2026, 6, 1))

        # 10 / 3 = 3.333...
        # Line 0: 3.33
        # Line 1: 3.33
        # Line 2: 10.00 - (3.33 + 3.33) = 3.34 (gets the rounding remainder!)
        self.assertEqual(res.line_allocations[0].subscription_discount_amount, Decimal("3.33"))
        self.assertEqual(res.line_allocations[1].subscription_discount_amount, Decimal("3.33"))
        self.assertEqual(res.line_allocations[2].subscription_discount_amount, Decimal("3.34"))
        self.assertEqual(sum(a.subscription_discount_amount for a in res.line_allocations), Decimal("10.00"))

    def test_usage_limit_exhaustion_single_thread(self):
        """Discount stops being eligible once usage_limit is reached."""
        disc = Discount.objects.create(
            name="Limited Discount",
            kind=DiscountKind.FIXED,
            value=Decimal("50.00"),
            usage_limit=2,
            used_count=1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.SUBSCRIPTION,
        )

        invoice1 = Invoice.objects.create(
            subscription=self.subscription,
            customer=self.customer,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            invoice_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
        )
        invoice2 = Invoice.objects.create(
            subscription=self.subscription,
            customer=self.customer,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            invoice_date=date(2026, 2, 1),
            due_date=date(2026, 2, 16),
        )

        # 2nd redemption succeeds (reaches limit 2)
        success1 = redeem(disc, invoice1)
        self.assertTrue(success1)
        self.assertEqual(disc.used_count, 2)
        self.assertEqual(DiscountRedemption.objects.filter(discount=disc).count(), 1)

        # 3rd redemption must fail (exhausted)
        success2 = redeem(disc, invoice2)
        self.assertFalse(success2)
        self.assertEqual(disc.used_count, 2)
        self.assertEqual(DiscountRedemption.objects.filter(discount=disc).count(), 1)


class ParallelRedemptionTests(TransactionTestCase):
    """TransactionTestCase allows parallel database connections/transactions."""
    def test_two_parallel_redemptions_of_the_last_use(self):
        """Two parallel redemptions of the last use: exactly one succeeds and one fails."""
        customer = Customer.objects.create(name="Concurrency Corp")
        plan = Plan.objects.create(
            name="Test Plan",
            price=Decimal("100.00"),
            interval="monthly",
            valid_from=date(2026, 1, 1),
        )
        subscription = Subscription.objects.create(
            number="SUB-2026-CONCURR",
            customer=customer,
            plan=plan,
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )
        disc = Discount.objects.create(
            name="One Use Left",
            kind=DiscountKind.FIXED,
            value=Decimal("10.00"),
            usage_limit=1,
            used_count=0,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.SUBSCRIPTION,
        )
        inv1 = Invoice.objects.create(
            subscription=subscription,
            customer=customer,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            invoice_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
        )
        inv2 = Invoice.objects.create(
            subscription=subscription,
            customer=customer,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            invoice_date=date(2026, 2, 1),
            due_date=date(2026, 2, 16),
        )

        def attempt_redeem(invoice):
            connection.close()  # Ensure each thread uses its own DB connection
            return redeem(disc, invoice)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(attempt_redeem, inv1)
            future2 = executor.submit(attempt_redeem, inv2)
            res1 = future1.result()
            res2 = future2.result()

        results = [res1, res2]
        self.assertEqual(results.count(True), 1, "Exactly one parallel redemption must succeed")
        self.assertEqual(results.count(False), 1, "Exactly one parallel redemption must fail")

        disc.refresh_from_db()
        self.assertEqual(disc.used_count, 1)
        self.assertEqual(DiscountRedemption.objects.filter(discount=disc).count(), 1)
