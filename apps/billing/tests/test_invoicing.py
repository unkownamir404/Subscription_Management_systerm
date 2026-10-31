from datetime import date
from decimal import Decimal
from django.test import TestCase
from apps.accounts.models import Customer
from apps.billing.models import Invoice
from apps.billing.services.invoicing import InvoiceDraft, InvoiceLineDraft, build_invoice_draft, compute_period_end
from apps.catalog.models import Discount, DiscountKind, DiscountScope, Plan, PlanInterval, Product, ProductType, ProductVariant
from apps.subscriptions.models import Subscription, SubscriptionLine


class InvoicingServiceTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name="Globex Corp")
        self.plan = Plan.objects.create(
            name="Cloud ERP",
            price=Decimal("1500.00"),
            interval=PlanInterval.MONTHLY,
            interval_count=1,
            valid_from=date(2026, 1, 1),
        )
        self.subscription = Subscription.objects.create(
            number="SUB-2026-INVOICING",
            customer=self.customer,
            plan=self.plan,
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
            payment_terms_days=15,
        )
        self.prod_main = Product.objects.create(
            name="ERP Core",
            product_type=ProductType.SOFTWARE,
            sales_price=Decimal("1500.00"),
        )
        self.prod_addon = Product.objects.create(
            name="Backup Storage",
            product_type=ProductType.ADDON,
            sales_price=Decimal("200.00"),
        )
        self.variant = ProductVariant.objects.create(
            product=self.prod_main,
            attribute="Edition",
            value="Enterprise",
            extra_price=Decimal("500.00"),
        )
        self.line1 = SubscriptionLine.objects.create(
            subscription=self.subscription,
            product=self.prod_main,
            variant=self.variant,
            quantity=1,
            unit_price=Decimal("2000.00"),  # 1500 + 500
            tax_rate=Decimal("18.00"),
        )
        self.line2 = SubscriptionLine.objects.create(
            subscription=self.subscription,
            product=self.prod_addon,
            quantity=2,
            unit_price=Decimal("200.00"),  # subtotal = 400.00
            tax_rate=Decimal("18.00"),
        )

    def test_pure_function_does_not_write_to_database(self):
        """build_invoice_draft must be pure and never write to the database."""
        initial_invoice_count = Invoice.objects.count()
        draft = build_invoice_draft(self.subscription, period_start=date(2026, 1, 1))

        self.assertEqual(Invoice.objects.count(), initial_invoice_count)
        self.assertIsInstance(draft, InvoiceDraft)
        self.assertTrue(all(isinstance(l, InvoiceLineDraft) for l in draft.lines))

    def test_frozen_dataclasses_immutability(self):
        """Draft instances must be frozen dataclasses."""
        draft = build_invoice_draft(self.subscription, period_start=date(2026, 1, 1))
        with self.assertRaises(Exception):
            draft.subtotal = Decimal("9999.00")  # FrozenInstanceError

        with self.assertRaises(Exception):
            draft.lines[0].line_total = Decimal("0.00")

    def test_totals_reconciling_without_discounts(self):
        """Verify: total == subtotal - discount_total + tax_total."""
        draft = build_invoice_draft(self.subscription, period_start=date(2026, 1, 1))

        # Line 1: 2000.00 * 1 = 2000.00. Tax 18% = 360.00. Total = 2360.00
        # Line 2: 200.00 * 2 = 400.00. Tax 18% = 72.00. Total = 472.00
        # Subtotal = 2400.00, Discount = 0.00, Tax = 432.00, Total = 2832.00
        self.assertEqual(draft.subtotal, Decimal("2400.00"))
        self.assertEqual(draft.discount_total, Decimal("0.00"))
        self.assertEqual(draft.tax_total, Decimal("432.00"))
        self.assertEqual(draft.total, Decimal("2832.00"))
        self.assertEqual(draft.total, draft.subtotal - draft.discount_total + draft.tax_total)

    def test_totals_reconciling_with_complex_discounts_and_tax(self):
        """Reconciliation test with line & subscription discounts and taxes."""
        disc_prod = Discount.objects.create(
            name="Line 1 Discount",
            kind=DiscountKind.FIXED,
            value=Decimal("200.00"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.PRODUCTS,
        )
        disc_prod.products.add(self.prod_main)

        disc_sub = Discount.objects.create(
            name="10% Sub Discount",
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.SUBSCRIPTION,
        )

        draft = build_invoice_draft(self.subscription, period_start=date(2026, 1, 1))

        # Reconciles exactly:
        self.assertEqual(draft.total, draft.subtotal - draft.discount_total + draft.tax_total)
        self.assertTrue(draft.discount_total > Decimal("0.00"))
        self.assertTrue(draft.tax_total > Decimal("0.00"))

        # Each line also reconciles line_total == (line_sub - discount) + tax
        for line in draft.lines:
            expected_line_net = (line.quantity * line.unit_price) - line.discount_amount
            self.assertEqual(line.line_total, expected_line_net + line.tax_amount)

    def test_period_end_calculation_relativedelta(self):
        """period_end(n) = period_start(n+1) - 1 day."""
        cases = [
            ("Monthly Jan", date(2026, 1, 1), "monthly", 1, date(2026, 1, 31)),
            ("Monthly Feb Leap Year", date(2024, 2, 1), "monthly", 1, date(2024, 2, 29)),
            ("Monthly Feb Non-Leap", date(2026, 2, 1), "monthly", 1, date(2026, 2, 28)),
            ("Quarterly (3 months)", date(2026, 1, 1), "monthly", 3, date(2026, 3, 31)),
            ("Yearly", date(2026, 1, 1), "yearly", 1, date(2026, 12, 31)),
            ("Weekly", date(2026, 1, 1), "weekly", 1, date(2026, 1, 7)),
            ("Daily", date(2026, 1, 1), "daily", 1, date(2026, 1, 1)),
        ]

        for desc, start_dt, interval, count, expected_end in cases:
            with self.subTest(scenario=desc):
                calculated_end = compute_period_end(start_dt, interval, count)
                self.assertEqual(calculated_end, expected_end)
