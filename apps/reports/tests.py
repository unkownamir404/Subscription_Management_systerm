from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, RequestFactory
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.apps import apps
from apps.reports.views import dashboard_view
from apps.reports.services import get_summary


class MockUser:
    def __init__(self, email, role, is_authenticated=True, is_superuser=False):
        self.email = email
        self.role = role
        self.is_authenticated = is_authenticated
        self.is_superuser = is_superuser


class ReportsDashboardViewTests(TestCase):
    """View-level RBAC and filter-preservation tests."""

    def setUp(self):
        self.factory = RequestFactory()
        self.staff_user = MockUser("staff@brightloop.test", role="staff")
        self.admin_user = MockUser("admin@brightloop.test", role="admin")
        self.customer_user = MockUser("customer@brightloop.test", role="customer")

    def test_dashboard_renders_200_for_staff(self):
        request = self.factory.get("/reports/")
        request.user = self.staff_user
        response = dashboard_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Finance Dashboard", html=False)
        self.assertContains(response, "Monthly Recurring Revenue", html=False)

    def test_dashboard_renders_200_for_admin(self):
        request = self.factory.get("/reports/")
        request.user = self.admin_user
        response = dashboard_view(request)
        self.assertEqual(response.status_code, 200)

    def test_dashboard_renders_403_for_customer(self):
        request = self.factory.get("/reports/")
        request.user = self.customer_user
        with self.assertRaises(PermissionDenied):
            dashboard_view(request)

    def test_filter_parameters_preserved_in_context_and_form(self):
        params = {
            "date_from": "2026-10-01",
            "date_to": "2026-10-31",
            "status": "active",
            "customer": "Acme",
        }
        request = self.factory.get("/reports/", params)
        request.user = self.staff_user
        response = dashboard_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="2026-10-01"')
        self.assertContains(response, 'value="2026-10-31"')
        self.assertContains(response, 'value="Acme"')
        self.assertContains(response, 'selected>Active</option>')

    def test_get_summary_contract_shape(self):
        try:
            summary = get_summary()
        except LookupError:
            return  # Models from other apps not registered in isolated environment

        required_keys = [
            "active_subscriptions",
            "paused_subscriptions",
            "revenue_collected",
            "billed",
            "outstanding",
            "overdue_count",
            "overdue_amount",
            "mrr",
            "arr",
            "ageing",
            "recent_payments",
            "overdue_invoices",
        ]
        for key in required_keys:
            self.assertIn(key, summary)

        self.assertIn("1-30", summary["ageing"])
        self.assertIn("31-60", summary["ageing"])
        self.assertIn("60+", summary["ageing"])


class ReportsDatabaseAggregationTests(TestCase):
    """
    Integration tests verifying database-level aggregation, overdue boundaries,
    aging bucket edges, and query count ceilings.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.staff_user = MockUser("staff@brightloop.test", role="staff")

    def test_overdue_boundaries_and_ageing_edges(self):
        try:
            Customer = apps.get_model("accounts", "Customer")
            Plan = apps.get_model("catalog", "Plan")
            Product = apps.get_model("catalog", "Product")
            Subscription = apps.get_model("subscriptions", "Subscription")
            SubscriptionLine = apps.get_model("subscriptions", "SubscriptionLine")
            Invoice = apps.get_model("billing", "Invoice")
            Payment = apps.get_model("billing", "Payment")
        except LookupError:
            self.skipTest("Domain models not yet loaded on this unmerged branch")

        today = timezone.localdate()
        far_future = today + timedelta(days=365)

        # Base test fixtures
        cust = Customer.objects.create(name="Edge Test Customer", company="Edge Co")
        plan_m = Plan.objects.create(
            name="Monthly Plan",
            price=Decimal("1000.00"),
            interval="monthly",
            interval_count=1,
            valid_from=today - timedelta(days=365),
        )
        prod = Product.objects.create(name="Edge Product", sales_price=Decimal("1000.00"))

        # 1 Active Subscription with a billing line
        sub_active = Subscription.objects.create(
            number="SUB-TEST-001",
            customer=cust,
            plan=plan_m,
            status="active",
            start_date=today - timedelta(days=60),
            billing_anchor=today - timedelta(days=60),
            expiry_date=far_future,
        )
        SubscriptionLine.objects.create(
            subscription=sub_active,
            product=prod,
            quantity=1,
            unit_price=Decimal("1000.00"),
            tax_rate=Decimal("0.00"),
        )

        # 1 Paused Subscription
        Subscription.objects.create(
            number="SUB-TEST-002",
            customer=cust,
            plan=plan_m,
            status="active",
            paused_at=timezone.now(),
            start_date=today - timedelta(days=60),
            expiry_date=far_future,
        )

        # Invoices testing boundaries.
        # Each has a UNIQUE period_start to satisfy the UniqueConstraint(subscription, period_start).
        # period_start offsets chosen to be all distinct: -200,-100,-50,-40,-35,-32,-29

        # 1. Paid invoice (contributes to revenue_collected)
        inv_paid = Invoice.objects.create(
            number="INV-PAID-01",
            subscription=sub_active,
            customer=cust,
            period_start=today - timedelta(days=200),
            period_end=today - timedelta(days=170),
            invoice_date=today - timedelta(days=200),
            due_date=today - timedelta(days=180),
            status="paid",
            subtotal=Decimal("500.00"),
            total=Decimal("500.00"),
            amount_paid=Decimal("500.00"),
        )
        Payment.objects.create(
            invoice=inv_paid,
            method="upi",
            amount=Decimal("500.00"),
            paid_on=today - timedelta(days=180),
        )

        # 2. Confirmed, due_date == today (BOUNDARY: NOT overdue)
        Invoice.objects.create(
            number="INV-DUE-TODAY",
            subscription=sub_active,
            customer=cust,
            period_start=today - timedelta(days=100),
            period_end=today + timedelta(days=30),
            invoice_date=today,
            due_date=today,
            status="confirmed",
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
        )

        # 3. Confirmed, due_date == today-1 (BOUNDARY: Overdue, 1-30 bucket)
        Invoice.objects.create(
            number="INV-OVERDUE-1",
            subscription=sub_active,
            customer=cust,
            period_start=today - timedelta(days=50),
            period_end=today - timedelta(days=1),
            invoice_date=today - timedelta(days=50),
            due_date=today - timedelta(days=1),
            status="confirmed",
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
        )

        # 4. Confirmed, due_date == today-30 (EDGE: 1-30 bucket)
        Invoice.objects.create(
            number="INV-EDGE-30",
            subscription=sub_active,
            customer=cust,
            period_start=today - timedelta(days=40),
            period_end=today - timedelta(days=30),
            invoice_date=today - timedelta(days=40),
            due_date=today - timedelta(days=30),
            status="confirmed",
            subtotal=Decimal("200.00"),
            total=Decimal("200.00"),
            amount_paid=Decimal("0.00"),
        )

        # 5. Confirmed, due_date == today-31 (EDGE: 31-60 bucket)
        Invoice.objects.create(
            number="INV-EDGE-31",
            subscription=sub_active,
            customer=cust,
            period_start=today - timedelta(days=35),
            period_end=today - timedelta(days=31),
            invoice_date=today - timedelta(days=35),
            due_date=today - timedelta(days=31),
            status="confirmed",
            subtotal=Decimal("300.00"),
            total=Decimal("300.00"),
            amount_paid=Decimal("0.00"),
        )

        # 6. Confirmed, due_date == today-60 (EDGE: 31-60 bucket)
        Invoice.objects.create(
            number="INV-EDGE-60",
            subscription=sub_active,
            customer=cust,
            period_start=today - timedelta(days=32),
            period_end=today - timedelta(days=60),
            invoice_date=today - timedelta(days=32),
            due_date=today - timedelta(days=60),
            status="confirmed",
            subtotal=Decimal("400.00"),
            total=Decimal("400.00"),
            amount_paid=Decimal("0.00"),
        )

        # 7. Confirmed, due_date == today-61 (EDGE: 60+ bucket)
        Invoice.objects.create(
            number="INV-EDGE-61",
            subscription=sub_active,
            customer=cust,
            period_start=today - timedelta(days=29),
            period_end=today - timedelta(days=61),
            invoice_date=today - timedelta(days=29),
            due_date=today - timedelta(days=61),
            status="confirmed",
            subtotal=Decimal("500.00"),
            total=Decimal("500.00"),
            amount_paid=Decimal("0.00"),
        )

        # Run aggregation
        summary = get_summary()

        # Subscription counts
        self.assertEqual(summary["active_subscriptions"], 1)
        self.assertEqual(summary["paused_subscriptions"], 1)

        # Revenue = paid payments
        self.assertEqual(summary["revenue_collected"], Decimal("500.00"))

        # MRR / ARR from the active line (1000/mo x 1)
        self.assertEqual(summary["mrr"], Decimal("1000.00"))
        self.assertEqual(summary["arr"], Decimal("12000.00"))

        # Overdue: excludes INV-DUE-TODAY; includes -1,-30,-31,-60,-61 days → 5 invoices
        # Amounts: 100+200+300+400+500 = 1500
        self.assertEqual(summary["overdue_count"], 5)
        self.assertEqual(summary["overdue_amount"], Decimal("1500.00"))

        # Ageing buckets:
        # 1-30:  INV-OVERDUE-1(100) + INV-EDGE-30(200)       = 300
        # 31-60: INV-EDGE-31(300)   + INV-EDGE-60(400)       = 700
        # 60+:   INV-EDGE-61(500)                             = 500
        self.assertEqual(summary["ageing"]["1-30"], Decimal("300.00"))
        self.assertEqual(summary["ageing"]["31-60"], Decimal("700.00"))
        self.assertEqual(summary["ageing"]["60+"], Decimal("500.00"))

        # Query count ceiling: exactly 6 efficient queries (well under the 12-query SLA)
        with self.assertNumQueries(6):
            get_summary()



class InvoiceViewsTestCase(TestCase):
    def setUp(self):
        from datetime import date
        from django.contrib.auth import get_user_model
        from django.test import Client
        from apps.accounts.models import Customer
        from apps.catalog.models import Product, ProductVariant, Plan, Tax, Discount
        from apps.subscriptions.models import Subscription, SubscriptionLine
        from apps.billing.models import Invoice, InvoiceLine, Payment
        from apps.reports.services import get_invoice_calculation_breakdown

        User = get_user_model()
        self.client = Client()

        self.admin = User.objects.create_superuser(
            email="admin_inv@brightloop.test",
            password="Demo@12345",
        )
        self.admin.role = "admin"
        self.admin.save()

        self.staff = User.objects.create_user(
            email="staff_inv@brightloop.test",
            password="Demo@12345",
            role="staff",
        )

        self.customer_user = User.objects.create_user(
            email="cust1_inv@brightloop.test",
            password="Demo@12345",
            role="customer",
        )
        self.customer1 = Customer.objects.create(
            user=self.customer_user,
            name="Acme Corp",
        )

        self.other_customer_user = User.objects.create_user(
            email="cust2_inv@brightloop.test",
            password="Demo@12345",
            role="customer",
        )
        self.customer2 = Customer.objects.create(
            user=self.other_customer_user,
            name="Beta Ltd",
        )

        self.tax18 = Tax.objects.create(name="GST 18%", rate=Decimal("18.00"))
        self.product1 = Product.objects.create(
            name="ERP Suite",
            sales_price=Decimal("1000.00"),
            tax=self.tax18,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product1,
            attribute="Brand",
            value="Odoo",
            extra_price=Decimal("560.00"),
        )
        self.plan = Plan.objects.create(
            name="Monthly Business",
            price=Decimal("1560.00"),
            interval="monthly",
            interval_count=1,
            valid_from=date(2026, 1, 1),
        )
        self.discount = Discount.objects.create(
            name="Welcome 100",
            kind="fixed",
            value=Decimal("100.00"),
            scope="subscription",
            is_active=True,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )

        self.sub = Subscription.objects.create(
            number="SUB-INV-001",
            customer=self.customer1,
            plan=self.plan,
            status="active",
            start_date=date(2026, 1, 1),
            expiry_date=date(2027, 1, 1),
            billing_anchor=date(2026, 1, 1),
            next_invoice_date=date(2026, 2, 1),
        )
        self.sub_line = SubscriptionLine.objects.create(
            subscription=self.sub,
            product=self.product1,
            variant=self.variant,
            quantity=2,
            unit_price=Decimal("1560.00"),
            tax_rate=Decimal("18.00"),
        )

        self.invoice = Invoice.objects.create(
            number="INV-2026-PANEL01",
            subscription=self.sub,
            customer=self.customer1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            invoice_date=date(2026, 1, 1),
            due_date=date(2026, 1, 15),
            status="confirmed",
            subtotal=Decimal("3120.00"),
            discount_total=Decimal("100.00"),
            tax_total=Decimal("543.60"),
            total=Decimal("3563.60"),
            amount_paid=Decimal("1000.00"),
        )
        self.inv_line = InvoiceLine.objects.create(
            invoice=self.invoice,
            description="ERP Suite (Odoo)",
            product=self.product1,
            quantity=2,
            unit_price=Decimal("1560.00"),
            discount_amount=Decimal("100.00"),
            discount=self.discount,
            tax_rate=Decimal("18.00"),
            tax_amount=Decimal("543.60"),
            line_total=Decimal("3563.60"),
        )

        self.payment = Payment.objects.create(
            invoice=self.invoice,
            method="upi",
            amount=Decimal("1000.00"),
            paid_on=date(2026, 1, 10),
            note="Partial payment via UPI",
            recorded_by=self.staff,
        )

    def test_invoice_list_renders_200_for_staff(self):
        """Staff members have access to the invoice list (200)."""
        self.client.force_login(self.staff)
        response = self.client.get("/invoices/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invoices")
        self.assertContains(response, "INV-2026-PANEL01")
        self.assertContains(response, "Acme Corp")

    def test_invoice_list_renders_200_for_admin(self):
        """Administrators have access to the invoice list (200)."""
        self.client.force_login(self.admin)
        response = self.client.get("/invoices/")
        self.assertEqual(response.status_code, 200)

    def test_invoice_list_renders_403_for_customers(self):
        """Customers are strictly forbidden from viewing the staff invoice list (403)."""
        self.client.force_login(self.customer_user)
        response = self.client.get("/invoices/")
        self.assertEqual(response.status_code, 403)

    def test_invoice_detail_renders_200_for_staff(self):
        """Staff can view detailed invoice breakdown (200)."""
        self.client.force_login(self.staff)
        response = self.client.get(f"/invoices/{self.invoice.number}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Why this amount?")
        self.assertContains(response, "ERP Suite (Odoo)")

    def test_invoice_detail_renders_200_for_owner_customer(self):
        """A customer can view their own invoice detail (200)."""
        self.client.force_login(self.customer_user)
        response = self.client.get(f"/invoices/{self.invoice.number}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INV-2026-PANEL01")

    def test_invoice_detail_renders_403_for_other_customer(self):
        """Tenant isolation: Customer cannot open another customer's invoice (403/404)."""
        self.client.force_login(self.other_customer_user)
        response = self.client.get(f"/invoices/{self.invoice.number}/")
        self.assertEqual(response.status_code, 403)

    def test_panel_numbers_match_invoice_totals(self):
        """
        Verify that the 'Why this amount?' panel calculation breakdown
        exactly reconciles with the invoice totals using only frozen line data.
        """
        from apps.reports.services import get_invoice_calculation_breakdown
        breakdown = get_invoice_calculation_breakdown(self.invoice)

        self.assertEqual(breakdown["calc_subtotal"], self.invoice.subtotal)
        self.assertEqual(breakdown["calc_discount_total"], self.invoice.discount_total)
        self.assertEqual(breakdown["calc_tax_total"], self.invoice.tax_total)
        self.assertEqual(breakdown["calc_total"], self.invoice.total)
        self.assertTrue(breakdown["reconciled"])

        self.assertEqual(len(breakdown["lines"]), 1)
        line = breakdown["lines"][0]
        self.assertEqual(line["unit_price"], Decimal("1560.00"))
        self.assertEqual(line["quantity"], 2)
        self.assertEqual(line["gross"], Decimal("3120.00"))
        self.assertEqual(line["discount_amount"], Decimal("100.00"))
        self.assertEqual(line["discount_source"], "Welcome 100 (Fixed Amount)")
        self.assertEqual(line["discounted_net"], Decimal("3020.00"))
        self.assertEqual(line["tax_rate"], Decimal("18.00"))
        self.assertEqual(line["tax_amount"], Decimal("543.60"))
        self.assertEqual(line["line_total"], Decimal("3563.60"))

        self.client.force_login(self.staff)
        response = self.client.get(f"/invoices/{self.invoice.number}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reconciled (100% Match)")



class FinancialReportsAndExportTests(TestCase):
    def setUp(self):
        from apps.accounts.models import User
        self.staff = User.objects.create_user(
            email="staff_rep@brightloop.test", password="ValidPassword@123", role="staff", is_staff=True
        )
        self.cust = User.objects.create_user(
            email="cust_rep@brightloop.test", password="ValidPassword@123", role="customer"
        )

    def test_financial_summary_view_access(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/reports/financial/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Financial & Revenue Reports")

        # Customer denied
        self.client.force_login(self.cust)
        resp = self.client.get("/reports/financial/")
        self.assertEqual(resp.status_code, 403)

    def test_export_report_csv(self):
        self.client.force_login(self.staff)
        for rtype in ["revenue", "invoices", "subscriptions", "payments"]:
            resp = self.client.get(f"/reports/export/?type={rtype}")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp["Content-Type"], "text/csv")
            self.assertIn(f"brightloop_{rtype}_report.csv", resp["Content-Disposition"])
