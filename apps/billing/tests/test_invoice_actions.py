from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Customer
from apps.catalog.models import Plan, Tax, Product
from apps.subscriptions.models import Subscription, SubscriptionLine
from apps.billing.models import (
    Invoice,
    InvoiceCounter,
    InvoiceLine,
    InvoiceStatus,
    Payment,
    PaymentMethod,
)
from apps.billing.services.invoice_actions import (
    confirm_invoice,
    cancel_invoice,
    mark_sent,
    record_payment,
)

User = get_user_model()


class InvoiceActionsServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="staff_action@brightloop.test",
            password="DemoPassword@123",
            role="staff",
            is_staff=True,
        )
        self.customer_user = User.objects.create_user(
            email="client_action@brightloop.test",
            password="DemoPassword@123",
            role="customer",
        )
        self.customer = Customer.objects.create(
            user=self.customer_user,
            name="Alpha Corp",
            billing_address="123 Street",
        )
        self.plan = Plan.objects.create(
            name="Standard Monthly",
            price=Decimal("1000.00"),
            interval="monthly",
            interval_count=1,
            valid_from=date(2026, 1, 1),
        )
        self.subscription = Subscription.objects.create(
            number="SUB-2026-999001",
            customer=self.customer,
            plan=self.plan,
            status="active",
            start_date=date(2026, 1, 1),
            expiry_date=date(2027, 1, 1),
            billing_anchor=date(2026, 1, 1),
            next_invoice_date=date(2026, 2, 1),
        )

    def _create_draft_invoice(self, total=Decimal("1000.00"), period_start=date(2026, 1, 1)):
        inv = Invoice.objects.create(
            subscription=self.subscription,
            customer=self.customer,
            period_start=period_start,
            period_end=period_start + timedelta(days=30),
            invoice_date=period_start,
            due_date=period_start + timedelta(days=15),
            status=InvoiceStatus.DRAFT,
            subtotal=total,
            total=total,
            amount_paid=Decimal("0.00"),
        )
        InvoiceLine.objects.create(
            invoice=inv,
            description="Service line",
            quantity=1,
            unit_price=total,
            tax_rate=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            line_total=total,
        )
        return inv

    def test_numbering_gapless_and_unique_sequential_confirms(self):
        """
        Invoice numbering is gapless and unique under sequential confirms
        assigned from InvoiceCounter under row lock.
        """
        inv1 = self._create_draft_invoice(period_start=date(2026, 1, 1))
        inv2 = self._create_draft_invoice(period_start=date(2026, 2, 1))

        confirmed1 = confirm_invoice(inv1, user=self.user)
        confirmed2 = confirm_invoice(inv2, user=self.user)

        self.assertEqual(confirmed1.status, InvoiceStatus.CONFIRMED)
        self.assertEqual(confirmed2.status, InvoiceStatus.CONFIRMED)
        self.assertEqual(confirmed1.number, "INV-2026-000001")
        self.assertEqual(confirmed2.number, "INV-2026-000002")

        counter = InvoiceCounter.objects.get(key="INV-2026")
        self.assertEqual(counter.last_value, 2)

    def test_illegal_transitions_rejected(self):
        """
        Only draft invoices can be confirmed.
        Only draft and confirmed invoices without payments can be cancelled.
        """
        inv = self._create_draft_invoice()
        confirm_invoice(inv, user=self.user)

        # Confirming an already confirmed invoice must fail
        with self.assertRaises(ValidationError) as ctx:
            confirm_invoice(inv, user=self.user)
        self.assertIn("Only draft invoices can be confirmed", str(ctx.exception))

        # Cancelling confirmed invoice works
        cancel_invoice(inv, user=self.user)
        self.assertEqual(inv.status, InvoiceStatus.CANCELLED)

        # Confirming cancelled invoice must fail
        with self.assertRaises(ValidationError):
            confirm_invoice(inv, user=self.user)

        # Cancelling already cancelled invoice must fail
        with self.assertRaises(ValidationError):
            cancel_invoice(inv, user=self.user)

    def test_cancel_blocked_after_partial_payment(self):
        """
        Cancel is blocked if amount_paid > 0.
        """
        inv = self._create_draft_invoice(total=Decimal("1000.00"))
        confirm_invoice(inv, user=self.user)

        record_payment(
            inv,
            method=PaymentMethod.BANK_TRANSFER,
            amount=Decimal("300.00"),
            user=self.user,
        )
        self.assertEqual(inv.amount_paid, Decimal("300.00"))

        with self.assertRaises(ValidationError) as ctx:
            cancel_invoice(inv, user=self.user)
        self.assertIn("Cannot cancel an invoice with payments recorded", str(ctx.exception))
        self.assertEqual(inv.status, InvoiceStatus.CONFIRMED)

    def test_overpayment_rejected(self):
        """
        Reject payment when amount <= 0 or amount > remaining balance.
        """
        inv = self._create_draft_invoice(total=Decimal("500.00"))
        confirm_invoice(inv, user=self.user)

        # Zero payment rejected
        with self.assertRaises(ValidationError):
            record_payment(inv, method=PaymentMethod.CARD, amount=Decimal("0.00"), user=self.user)

        # Negative payment rejected
        with self.assertRaises(ValidationError):
            record_payment(inv, method=PaymentMethod.UPI, amount=Decimal("-10.00"), user=self.user)

        # Overpayment rejected
        with self.assertRaises(ValidationError) as ctx:
            record_payment(inv, method=PaymentMethod.BANK_TRANSFER, amount=Decimal("500.01"), user=self.user)
        self.assertIn("exceeds remaining balance", str(ctx.exception))

        # Float rejected (must be Decimal/string)
        with self.assertRaises(TypeError):
            record_payment(inv, method=PaymentMethod.CASH, amount=50.0, user=self.user)

    def test_partial_then_full_payment_flips_to_paid(self):
        """
        Partial payment leaves invoice confirmed; settling remainder flips invoice to paid.
        """
        inv = self._create_draft_invoice(total=Decimal("800.00"))
        confirm_invoice(inv, user=self.user)

        # 1. Partial payment 300
        p1 = record_payment(inv, method=PaymentMethod.BANK_TRANSFER, amount=Decimal("300.00"), user=self.user)
        self.assertEqual(p1.amount, Decimal("300.00"))
        self.assertEqual(inv.amount_paid, Decimal("300.00"))
        self.assertEqual(inv.status, InvoiceStatus.CONFIRMED)

        # 2. Settling payment 500
        p2 = record_payment(inv, method=PaymentMethod.UPI, amount=Decimal("500.00"), user=self.user)
        self.assertEqual(p2.amount, Decimal("500.00"))
        self.assertEqual(inv.amount_paid, Decimal("800.00"))
        self.assertEqual(inv.status, InvoiceStatus.PAID)

        # Further payment on paid invoice rejected
        with self.assertRaises(ValidationError) as ctx:
            record_payment(inv, method=PaymentMethod.CASH, amount=Decimal("10.00"), user=self.user)
        self.assertIn("already fully paid", str(ctx.exception))

    def test_payment_on_draft_is_rejected(self):
        """
        Payment recording requires confirmed status; draft invoices reject payments.
        """
        inv = self._create_draft_invoice(total=Decimal("500.00"))
        with self.assertRaises(ValidationError) as ctx:
            record_payment(inv, method=PaymentMethod.BANK_TRANSFER, amount=Decimal("100.00"), user=self.user)
        self.assertIn("cannot be recorded on draft invoices", str(ctx.exception))
        self.assertEqual(Payment.objects.filter(invoice=inv).count(), 0)

    def test_mark_sent_sets_timestamp_without_status_change(self):
        """
        mark_sent updates sent_at timestamp; leaves invoice status untouched.
        """
        inv = self._create_draft_invoice()
        self.assertIsNone(inv.sent_at)
        mark_sent(inv)
        self.assertIsNotNone(inv.sent_at)
        self.assertEqual(inv.status, InvoiceStatus.DRAFT)


class InvoiceViewsAndPermissionsTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Users
        self.admin = User.objects.create_superuser(
            email="admin_v@brightloop.test",
            password="AdminPassword@123",
            role="admin",
        )
        self.staff = User.objects.create_user(
            email="staff_v@brightloop.test",
            password="StaffPassword@123",
            role="staff",
            is_staff=True,
        )
        self.cust_user_a = User.objects.create_user(
            email="cust_a@brightloop.test",
            password="CustPassword@123",
            role="customer",
        )
        self.cust_user_b = User.objects.create_user(
            email="cust_b@brightloop.test",
            password="CustPassword@123",
            role="customer",
        )

        self.cust_a = Customer.objects.create(
            user=self.cust_user_a,
            name="Customer A Org",
            billing_address="Address A",
        )
        self.cust_b = Customer.objects.create(
            user=self.cust_user_b,
            name="Customer B Org",
            billing_address="Address B",
        )

        self.plan = Plan.objects.create(
            name="Plan V",
            price=Decimal("1000.00"),
            interval="monthly",
            interval_count=1,
            valid_from=date(2026, 1, 1),
        )
        self.sub_a = Subscription.objects.create(
            number="SUB-V-001",
            customer=self.cust_a,
            plan=self.plan,
            status="active",
            start_date=date(2026, 1, 1),
            expiry_date=date(2027, 1, 1),
        )
        self.sub_b = Subscription.objects.create(
            number="SUB-V-002",
            customer=self.cust_b,
            plan=self.plan,
            status="active",
            start_date=date(2026, 1, 1),
            expiry_date=date(2027, 1, 1),
        )

        self.inv_a = Invoice.objects.create(
            subscription=self.sub_a,
            customer=self.cust_a,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            invoice_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
            status=InvoiceStatus.DRAFT,
            subtotal=Decimal("1000.00"),
            total=Decimal("1000.00"),
            amount_paid=Decimal("0.00"),
        )
        self.inv_b = Invoice.objects.create(
            subscription=self.sub_b,
            customer=self.cust_b,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            invoice_date=date(2026, 1, 1),
            due_date=date(2026, 1, 16),
            status=InvoiceStatus.DRAFT,
            subtotal=Decimal("2000.00"),
            total=Decimal("2000.00"),
            amount_paid=Decimal("0.00"),
        )

    def test_for_user_queryset_filtering(self):
        """
        Invoice.objects.for_user(user) returns:
        - Admin/Staff: all invoices
        - Customer: only own invoices
        - Anonymous: none
        """
        self.assertEqual(Invoice.objects.for_user(self.admin).count(), 2)
        self.assertEqual(Invoice.objects.for_user(self.staff).count(), 2)
        self.assertEqual(Invoice.objects.for_user(self.cust_user_a).count(), 1)
        self.assertEqual(Invoice.objects.for_user(self.cust_user_a).first(), self.inv_a)
        self.assertEqual(Invoice.objects.for_user(None).count(), 0)

    def test_cross_customer_access_returns_404(self):
        """
        Cross-customer access on print or action URLs returns 404.
        """
        self.client.force_login(self.cust_user_a)

        # Print Customer B's invoice -> 404
        response = self.client.get(f"/invoices/{self.inv_b.id}/print/")
        self.assertEqual(response.status_code, 404)

        # Confirm Customer B's invoice -> 404
        response = self.client.post(f"/invoices/{self.inv_b.id}/confirm/")
        self.assertEqual(response.status_code, 404)

        # Payment on Customer B's invoice -> 404
        response = self.client.post(f"/invoices/{self.inv_b.id}/payments/", {
            "method": "bank_transfer",
            "amount": "100.00",
        })
        self.assertEqual(response.status_code, 404)

    def test_wrong_role_on_actions_returns_403(self):
        """
        Customer attempting staff/admin action on own invoice returns 403 Forbidden.
        """
        self.client.force_login(self.cust_user_a)

        # Customer attempts confirm on own invoice -> 403
        response = self.client.post(f"/invoices/{self.inv_a.id}/confirm/")
        self.assertEqual(response.status_code, 403)

        # Customer attempts cancel on own invoice -> 403
        response = self.client.post(f"/invoices/{self.inv_a.id}/cancel/")
        self.assertEqual(response.status_code, 403)

        # Customer attempts send on own invoice -> 403
        response = self.client.post(f"/invoices/{self.inv_a.id}/send/")
        self.assertEqual(response.status_code, 403)

        # Customer attempts payment recording on own invoice -> 403
        response = self.client.post(f"/invoices/{self.inv_a.id}/payments/", {
            "method": "bank_transfer",
            "amount": "100.00",
        })
        self.assertEqual(response.status_code, 403)

    def test_customer_can_print_own_invoice(self):
        """
        Customer can view/print own invoice: returns 200.
        """
        self.client.force_login(self.cust_user_a)
        response = self.client.get(f"/invoices/{self.inv_a.id}/print/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "billing/invoice_print.html")

    def test_staff_and_admin_can_perform_actions(self):
        """
        Staff can confirm, send, record payment, and print invoices.
        """
        self.client.force_login(self.staff)

        # 1. Confirm
        res = self.client.post(f"/invoices/{self.inv_a.id}/confirm/")
        self.assertEqual(res.status_code, 302)
        self.inv_a.refresh_from_db()
        self.assertEqual(self.inv_a.status, InvoiceStatus.CONFIRMED)
        self.assertTrue(self.inv_a.number.startswith("INV-2026-"))

        # 2. Send
        res = self.client.post(f"/invoices/{self.inv_a.id}/send/")
        self.assertEqual(res.status_code, 302)
        self.inv_a.refresh_from_db()
        self.assertIsNotNone(self.inv_a.sent_at)

        # 3. Record Payment
        res = self.client.post(f"/invoices/{self.inv_a.id}/payments/", {
            "method": "bank_transfer",
            "amount": "1000.00",
            "paid_on": "2026-01-10",
            "note": "Settled in full via NEFT",
        })
        self.assertEqual(res.status_code, 302)
        self.inv_a.refresh_from_db()
        self.assertEqual(self.inv_a.status, InvoiceStatus.PAID)
        self.assertEqual(self.inv_a.amount_paid, Decimal("1000.00"))

        # 4. Print
        res = self.client.get(f"/invoices/{self.inv_a.id}/print/")
        self.assertEqual(res.status_code, 200)
