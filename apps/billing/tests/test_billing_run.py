from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from apps.accounts.models import Customer
from apps.billing.models import (
    BillingItemResult,
    BillingRun,
    BillingRunItem,
    DiscountRedemption,
    Invoice,
)
from apps.billing.services.billing_run import compute_period_start, run_billing
from apps.catalog.models import Discount, DiscountKind, DiscountScope, Plan, PlanInterval, Product, ProductType
from apps.subscriptions.models import Subscription, SubscriptionEvent, SubscriptionLine, SubscriptionStatus
from apps.subscriptions.services.lifecycle import activate


class LifecycleServiceTests(TestCase):
    def test_activate_subscription(self):
        """activate sets billing_anchor=start_date, periods_billed=0, next_invoice_date=start_date, status=active, logs event."""
        customer = Customer.objects.create(name="Customer Test")
        plan = Plan.objects.create(
            name="Plan Test",
            price=Decimal("100.00"),
            interval="monthly",
            valid_from=date(2026, 1, 1),
        )
        sub = Subscription.objects.create(
            number="SUB-ACTIVATE-01",
            customer=customer,
            plan=plan,
            status=SubscriptionStatus.DRAFT,
            start_date=date(2026, 2, 1),
            expiry_date=date(2026, 12, 31),
        )

        activated_sub = activate(sub)

        self.assertEqual(activated_sub.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(activated_sub.billing_anchor, date(2026, 2, 1))
        self.assertEqual(activated_sub.periods_billed, 0)
        self.assertEqual(activated_sub.next_invoice_date, date(2026, 2, 1))

        event = SubscriptionEvent.objects.filter(subscription=sub).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.from_status, SubscriptionStatus.DRAFT)
        self.assertEqual(event.to_status, SubscriptionStatus.ACTIVE)
        self.assertEqual(event.action, 'activate')


class BillingRunServiceTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name="Enterprise Client")
        self.plan = Plan.objects.create(
            name="Monthly Standard",
            price=Decimal("1000.00"),
            interval=PlanInterval.MONTHLY,
            interval_count=1,
            valid_from=date(2026, 1, 1),
        )
        self.product = Product.objects.create(
            name="Core Platform",
            product_type=ProductType.SOFTWARE,
            sales_price=Decimal("1000.00"),
        )

    def _create_active_sub(self, number, start_date, expiry_date, anchor=None, periods_billed=0, next_invoice_date=None):
        sub = Subscription.objects.create(
            number=number,
            customer=self.customer,
            plan=self.plan,
            status=SubscriptionStatus.ACTIVE,
            start_date=start_date,
            expiry_date=expiry_date,
            billing_anchor=anchor or start_date,
            periods_billed=periods_billed,
            next_invoice_date=next_invoice_date or start_date,
            payment_terms_days=15,
        )
        SubscriptionLine.objects.create(
            subscription=sub,
            product=self.product,
            quantity=1,
            unit_price=Decimal("1000.00"),
            tax_rate=Decimal("18.00"),
        )
        return sub

    def test_run_twice_creates_zero_new_invoices(self):
        """Running billing twice creates zero new invoices on the second run (idempotent)."""
        sub = self._create_active_sub(
            number="SUB-RUN-TWICE",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )

        # Run 1: Should create 1 invoice for Jan
        run1 = run_billing(as_of=date(2026, 1, 15))
        self.assertEqual(run1.created_count, 1)
        self.assertEqual(run1.skipped_count, 0)
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 1)

        # Run 2: Immediately running again on same date creates 0 new invoices
        run2 = run_billing(as_of=date(2026, 1, 15))
        self.assertEqual(run2.created_count, 0)
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 1)

    def test_three_missed_monthly_periods_create_three_invoices(self):
        """Catch-up loop: 3 missed monthly periods create exactly 3 invoices with correct period_start and period_end."""
        sub = self._create_active_sub(
            number="SUB-MISSED-3",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )

        # Run on March 15: Missed Jan 1, Feb 1, Mar 1
        run = run_billing(as_of=date(2026, 3, 15))
        self.assertEqual(run.created_count, 3)

        invoices = list(Invoice.objects.filter(subscription=sub).order_by('period_start'))
        self.assertEqual(len(invoices), 3)

        # Period 1: 2026-01-01 to 2026-01-31
        self.assertEqual(invoices[0].period_start, date(2026, 1, 1))
        self.assertEqual(invoices[0].period_end, date(2026, 1, 31))

        # Period 2: 2026-02-01 to 2026-02-28
        self.assertEqual(invoices[1].period_start, date(2026, 2, 1))
        self.assertEqual(invoices[1].period_end, date(2026, 2, 28))

        # Period 3: 2026-03-01 to 2026-03-31
        self.assertEqual(invoices[2].period_start, date(2026, 3, 1))
        self.assertEqual(invoices[2].period_end, date(2026, 3, 31))

        sub.refresh_from_db()
        self.assertEqual(sub.periods_billed, 3)
        self.assertEqual(sub.next_invoice_date, date(2026, 4, 1))

    def test_month_end_anchor_31_jan_gives_correct_feb_and_mar_starts(self):
        """Month-end anchor (31 Jan) gives correct 28/29 Feb and 31 Mar starts without calendar drift."""
        anchor = date(2026, 1, 31)

        # Direct verification of compute_period_start using relativedelta
        start_0 = compute_period_start(anchor, 0, 'monthly', 1)
        start_1 = compute_period_start(anchor, 1, 'monthly', 1)
        start_2 = compute_period_start(anchor, 2, 'monthly', 1)

        self.assertEqual(start_0, date(2026, 1, 31))
        self.assertEqual(start_1, date(2026, 2, 28))  # Non-leap year Feb
        self.assertEqual(start_2, date(2026, 3, 31))  # Preserves month-end 31!

        # Also verify in a leap year (2024)
        leap_anchor = date(2024, 1, 31)
        self.assertEqual(compute_period_start(leap_anchor, 1, 'monthly', 1), date(2024, 2, 29))

        # Test within full billing run
        sub = self._create_active_sub(
            number="SUB-MONTH-END",
            start_date=anchor,
            expiry_date=date(2026, 12, 31),
        )
        run_billing(as_of=date(2026, 4, 1))
        invoices = list(Invoice.objects.filter(subscription=sub).order_by('period_start'))
        self.assertEqual(len(invoices), 3)
        self.assertEqual(invoices[0].period_start, date(2026, 1, 31))
        self.assertEqual(invoices[1].period_start, date(2026, 2, 28))
        self.assertEqual(invoices[2].period_start, date(2026, 3, 31))

    def test_no_invoice_for_period_starting_after_expiry_date(self):
        """No invoice generated for a period starting after expiry_date."""
        sub = self._create_active_sub(
            number="SUB-EXPIRING",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 2, 15),  # Expires before March period start
        )

        run_billing(as_of=date(2026, 5, 1))

        invoices = list(Invoice.objects.filter(subscription=sub).order_by('period_start'))
        # Only Jan 1 and Feb 1 periods are <= expiry_date (2026-02-15)
        self.assertEqual(len(invoices), 2)
        self.assertEqual(invoices[0].period_start, date(2026, 1, 1))
        self.assertEqual(invoices[1].period_start, date(2026, 2, 1))

    def test_paused_subscriptions_are_skipped(self):
        """Subscriptions with paused_at set must be skipped."""
        sub = self._create_active_sub(
            number="SUB-PAUSED",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )
        sub.paused_at = date(2026, 1, 10)
        sub.save(update_fields=['paused_at'])

        run = run_billing(as_of=date(2026, 1, 15))
        self.assertEqual(run.created_count, 0)
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 0)

    def test_one_failing_subscription_does_not_block_others(self):
        """One subscription failing (e.g. exception during draft) does not block subsequent subscriptions."""
        sub_fail = self._create_active_sub(
            number="SUB-FAIL-01",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )
        sub_ok = self._create_active_sub(
            number="SUB-OK-02",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )

        original_build = apps_billing_build = __import__('apps.billing.services.billing_run', fromlist=['build_invoice_draft']).build_invoice_draft

        def mock_build(sub, period_start):
            if sub.number == "SUB-FAIL-01":
                raise ValueError("Simulated unexpected error on SUB-FAIL-01")
            return original_build(sub, period_start)

        with patch('apps.billing.services.billing_run.build_invoice_draft', side_effect=mock_build):
            run = run_billing(as_of=date(2026, 1, 15))

        self.assertEqual(run.created_count, 1)
        self.assertEqual(run.failed_count, 1)

        # sub_fail failed
        self.assertEqual(Invoice.objects.filter(subscription=sub_fail).count(), 0)
        failed_item = BillingRunItem.objects.filter(run=run, subscription=sub_fail).first()
        self.assertEqual(failed_item.result, BillingItemResult.FAILED)

        # sub_ok succeeded
        self.assertEqual(Invoice.objects.filter(subscription=sub_ok).count(), 1)
        ok_item = BillingRunItem.objects.filter(run=run, subscription=sub_ok).first()
        self.assertEqual(ok_item.result, BillingItemResult.CREATED)

    def test_discount_with_usage_limit_one_redeemed_only_once_across_double_run(self):
        """A discount with usage_limit=1 is redeemed only once across a double run or catch-up periods."""
        disc = Discount.objects.create(
            name="One-Time Welcome Discount",
            kind=DiscountKind.FIXED,
            value=Decimal("100.00"),
            usage_limit=1,
            used_count=0,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            scope=DiscountScope.SUBSCRIPTION,
        )

        sub = self._create_active_sub(
            number="SUB-ONE-TIME-DISC",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )

        # Run 1: Missed Jan and Feb
        run_billing(as_of=date(2026, 2, 15))

        disc.refresh_from_db()
        self.assertEqual(disc.used_count, 1)
        self.assertEqual(DiscountRedemption.objects.filter(discount=disc).count(), 1)

        # Run 2: Double run
        run_billing(as_of=date(2026, 3, 15))

        disc.refresh_from_db()
        self.assertEqual(disc.used_count, 1)
        self.assertEqual(DiscountRedemption.objects.filter(discount=disc).count(), 1)

    def test_dry_run_creates_nothing(self):
        """dry_run=True must write nothing to the database, returning in-memory planned counts."""
        sub = self._create_active_sub(
            number="SUB-DRY-RUN",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
        )

        initial_run_count = BillingRun.objects.count()
        initial_inv_count = Invoice.objects.count()
        initial_item_count = BillingRunItem.objects.count()

        dry_result = run_billing(as_of=date(2026, 2, 15), dry_run=True)

        self.assertTrue(dry_result.dry_run)
        self.assertEqual(dry_result.created_count, 2)  # Jan and Feb would be created
        self.assertIsNone(dry_result.id)  # Not persisted in DB

        # Verify DB records remain unchanged
        self.assertEqual(BillingRun.objects.count(), initial_run_count)
        self.assertEqual(Invoice.objects.count(), initial_inv_count)
        self.assertEqual(BillingRunItem.objects.count(), initial_item_count)

        sub.refresh_from_db()
        self.assertEqual(sub.periods_billed, 0)
        self.assertEqual(sub.next_invoice_date, date(2026, 1, 1))
