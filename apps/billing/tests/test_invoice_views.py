from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import Customer
from apps.catalog.models import Product, ProductVariant, Plan, Tax, Discount
from apps.subscriptions.models import Subscription, SubscriptionLine
from apps.billing.models import Invoice, InvoiceLine, Payment
from apps.reports.services import get_invoice_calculation_breakdown

User = get_user_model()


class InvoiceViewsTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Users
        self.admin = User.objects.create_superuser(
            email="admin_test@brightloop.test",
            password="Demo@12345",
        )
        self.admin.role = "admin"
        self.admin.save()

        self.staff = User.objects.create_user(
            email="staff_test@brightloop.test",
            password="Demo@12345",
            role="staff",
        )

        self.customer_user = User.objects.create_user(
            email="cust1_test@brightloop.test",
            password="Demo@12345",
            role="customer",
        )
        self.customer1 = Customer.objects.create(
            user=self.customer_user,
            name="Acme Corp",
        )

        self.other_customer_user = User.objects.create_user(
            email="cust2_test@brightloop.test",
            password="Demo@12345",
            role="customer",
        )
        self.customer2 = Customer.objects.create(
            user=self.other_customer_user,
            name="Beta Ltd",
        )

        # Catalog setup
        self.tax18 = Tax.objects.create(name="GST 18%", rate=Decimal("18.00"))
        self.tax5 = Tax.objects.create(name="GST 5%", rate=Decimal("5.00"))

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

        # Subscription
        self.sub = Subscription.objects.create(
            number="SUB-TEST-001",
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

        # Invoice with frozen lines
        # Line 1: Qty 2 @ 1560.00 = 3120.00 gross, discount 100.00 = 3020.00 net, tax 18% = 543.60, total = 3563.60
        self.invoice = Invoice.objects.create(
            number="INV-2026-TEST01",
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

        # Payment on invoice
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
        self.assertContains(response, "INV-2026-TEST01")
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
        self.assertContains(response, "INV-2026-TEST01")

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
        breakdown = get_invoice_calculation_breakdown(self.invoice)

        # Assert breakdown numbers match invoice summary totals
        self.assertEqual(breakdown["calc_subtotal"], self.invoice.subtotal)
        self.assertEqual(breakdown["calc_discount_total"], self.invoice.discount_total)
        self.assertEqual(breakdown["calc_tax_total"], self.invoice.tax_total)
        self.assertEqual(breakdown["calc_total"], self.invoice.total)
        self.assertTrue(breakdown["reconciled"])

        # Check line details
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

        # Verify rendered HTML in response
        self.client.force_login(self.staff)
        response = self.client.get(f"/invoices/{self.invoice.number}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reconciled (100% Match)")
