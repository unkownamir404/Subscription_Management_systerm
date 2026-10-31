from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from apps.accounts.models import Customer
from apps.catalog.models import Product, Plan, Tax
from apps.subscriptions.models import Subscription, SubscriptionLine
from apps.billing.models import Invoice, InvoiceLine, Payment, InvoiceStatus

User = get_user_model()


class CustomerPortalTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Users
        self.staff_user = User.objects.create_user(
            email="staff_portal@brightloop.test",
            password="Demo@12345",
            role="staff",
        )
        self.admin_user = User.objects.create_superuser(
            email="admin_portal@brightloop.test",
            password="Demo@12345",
        )
        self.admin_user.role = "admin"
        self.admin_user.save()

        # Customer 1
        self.cust1_user = User.objects.create_user(
            email="customer1@brightloop.test",
            password="Demo@12345",
            role="customer",
        )
        self.customer1 = Customer.objects.create(
            user=self.cust1_user,
            name="Alice Customer",
            company="Alice Corp",
        )

        # Customer 2
        self.cust2_user = User.objects.create_user(
            email="customer2@brightloop.test",
            password="Demo@12345",
            role="customer",
        )
        self.customer2 = Customer.objects.create(
            user=self.cust2_user,
            name="Bob Customer",
            company="Bob Industries",
        )

        # Catalog
        self.tax18 = Tax.objects.create(name="GST 18%", rate=Decimal("18.00"))
        self.product = Product.objects.create(
            name="Cloud Storage 100GB",
            sales_price=Decimal("1000.00"),
            tax=self.tax18,
        )
        self.plan = Plan.objects.create(
            name="Monthly Cloud",
            price=Decimal("1000.00"),
            interval="monthly",
            interval_count=1,
            valid_from=date(2026, 1, 1),
            allow_pause=True,
            allow_renew=True,
        )

        # Subscriptions
        self.sub1 = Subscription.objects.create(
            number="SUB-CUST1-001",
            customer=self.customer1,
            plan=self.plan,
            status="active",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
            billing_anchor=date(2026, 1, 1),
            next_invoice_date=date(2026, 2, 1),
        )
        self.sub1_line = SubscriptionLine.objects.create(
            subscription=self.sub1,
            product=self.product,
            quantity=1,
            unit_price=Decimal("1000.00"),
            tax_rate=Decimal("18.00"),
        )

        self.sub2 = Subscription.objects.create(
            number="SUB-CUST2-001",
            customer=self.customer2,
            plan=self.plan,
            status="active",
            start_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
            billing_anchor=date(2026, 1, 1),
            next_invoice_date=date(2026, 2, 1),
        )

        # Invoices
        self.inv1 = Invoice.objects.create(
            number="INV-CUST1-001",
            subscription=self.sub1,
            customer=self.customer1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            invoice_date=date(2026, 1, 1),
            due_date=date(2026, 1, 15),
            status="confirmed",
            subtotal=Decimal("1000.00"),
            tax_total=Decimal("180.00"),
            total=Decimal("1180.00"),
            amount_paid=Decimal("0.00"),
        )
        InvoiceLine.objects.create(
            invoice=self.inv1,
            description="Cloud Storage 100GB",
            product=self.product,
            quantity=1,
            unit_price=Decimal("1000.00"),
            tax_rate=Decimal("18.00"),
            tax_amount=Decimal("180.00"),
            line_total=Decimal("1180.00"),
        )

        self.inv2 = Invoice.objects.create(
            number="INV-CUST2-002",
            subscription=self.sub2,
            customer=self.customer2,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            invoice_date=date(2026, 1, 1),
            due_date=date(2026, 1, 15),
            status="confirmed",
            subtotal=Decimal("1000.00"),
            tax_total=Decimal("180.00"),
            total=Decimal("1180.00"),
            amount_paid=Decimal("0.00"),
        )

    def test_staff_users_are_redirected_away_from_portal(self):
        """Staff members accessing portal URLs must be redirected away (e.g. to /reports/)."""
        self.client.force_login(self.staff_user)

        res_dashboard = self.client.get("/portal/")
        self.assertEqual(res_dashboard.status_code, 302)
        self.assertIn("/reports/", res_dashboard.url)

        res_subs = self.client.get("/portal/subscriptions/")
        self.assertEqual(res_subs.status_code, 302)

        res_invs = self.client.get("/portal/invoices/")
        self.assertEqual(res_invs.status_code, 302)

    def test_admin_users_are_redirected_away_from_portal(self):
        """Admin users accessing portal URLs must be redirected away."""
        self.client.force_login(self.admin_user)

        res = self.client.get("/portal/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/reports/", res.url)

    def test_customer_can_see_own_portal_and_invoices(self):
        """Customer can access their own dashboard, subscriptions, and invoices (200)."""
        self.client.force_login(self.cust1_user)

        res = self.client.get("/portal/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Alice Customer")
        self.assertContains(res, "Upcoming Invoice Preview")
        self.assertContains(res, "SUB-CUST1-001")

        res_subs = self.client.get("/portal/subscriptions/")
        self.assertEqual(res_subs.status_code, 200)
        self.assertContains(res_subs, "SUB-CUST1-001")
        self.assertNotContains(res_subs, "SUB-CUST2-001")

        res_invs = self.client.get("/portal/invoices/")
        self.assertEqual(res_invs.status_code, 200)
        self.assertContains(res_invs, "INV-CUST1-001")
        self.assertNotContains(res_invs, "INV-CUST2-002")

    def test_customer_cannot_see_another_customers_invoice_404(self):
        """Security: Customer 1 accessing Customer 2's invoice payment page receives 404."""
        self.client.force_login(self.cust1_user)

        # By ID
        res_id = self.client.get(f"/portal/invoices/{self.inv2.id}/pay/")
        self.assertEqual(res_id.status_code, 404)

        # By invoice number
        res_num = self.client.get(f"/portal/invoices/{self.inv2.number}/pay/")
        self.assertEqual(res_num.status_code, 404)

    def test_customer_cannot_pay_another_customers_invoice_404(self):
        """Security: Customer 1 attempting to POST payment for Customer 2's invoice receives 404."""
        self.client.force_login(self.cust1_user)

        res = self.client.post(f"/portal/invoices/{self.inv2.id}/pay/")
        self.assertEqual(res.status_code, 404)

        # Verify inv2 is untouched
        self.inv2.refresh_from_db()
        self.assertEqual(self.inv2.amount_paid, Decimal("0.00"))
        self.assertEqual(self.inv2.status, InvoiceStatus.CONFIRMED)

    def test_customer_can_pay_own_invoice_calls_record_payment(self):
        """Customer can successfully pay their own invoice via mock card payment."""
        self.client.force_login(self.cust1_user)

        res = self.client.post(f"/portal/invoices/{self.inv1.id}/pay/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/portal/invoices/", res.url)

        # Verify payment recorded and invoice updated to paid
        self.inv1.refresh_from_db()
        self.assertEqual(self.inv1.amount_paid, Decimal("1180.00"))
        self.assertEqual(self.inv1.status, InvoiceStatus.PAID)

        # Verify Payment record
        payment = Payment.objects.filter(invoice=self.inv1).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.method, "card")
        self.assertEqual(payment.amount, Decimal("1180.00"))

    def test_customer_self_service_pause_and_renew(self):
        """Customer can pause, resume, and renew their own subscription; cross-customer returns 404."""
        self.client.force_login(self.cust1_user)

        # Pause own subscription
        res_pause = self.client.post(f"/portal/subscriptions/{self.sub1.id}/pause/")
        self.assertEqual(res_pause.status_code, 302)
        self.sub1.refresh_from_db()
        self.assertIsNotNone(self.sub1.paused_at)

        # Resume own subscription
        res_resume = self.client.post(f"/portal/subscriptions/{self.sub1.id}/pause/")
        self.assertEqual(res_resume.status_code, 302)
        self.sub1.refresh_from_db()
        self.assertIsNone(self.sub1.paused_at)

        # Cross-customer pause returns 404
        res_cross = self.client.post(f"/portal/subscriptions/{self.sub2.id}/pause/")
        self.assertEqual(res_cross.status_code, 404)
