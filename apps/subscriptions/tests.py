import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from apps.accounts.models import Customer
from apps.catalog.models import Plan, Product, ProductType
from apps.subscriptions.models import Subscription, SubscriptionStatus, QuotationTemplate, TemplateLine, SubscriptionLine
from apps.subscriptions.services import lifecycle
from apps.billing.models import Invoice, InvoiceStatus

User = get_user_model()


class SubscriptionsAndStaffTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            email="admin@test.com", password="Password123!", role="admin", is_staff=True, is_superuser=True
        )
        self.staff = User.objects.create_user(
            email="staff@test.com", password="Password123!", role="staff", is_staff=True
        )
        self.cust_user = User.objects.create_user(
            email="customer@test.com", password="Password123!", role="customer"
        )
        self.customer = Customer.objects.create(user=self.cust_user, name="Acme Corp")

        self.plan = Plan.objects.create(
            name="Pro Monthly",
            price=Decimal("100.00"),
            interval=Plan.Interval.MONTHLY,
            interval_count=1,
            valid_from=datetime.date(2026, 1, 1),
            allow_pause=True,
            allow_early_close=True,
        )
        self.product = Product.objects.create(
            name="Cloud Storage",
            product_type=ProductType.SERVICE,
            sales_price=Decimal("50.00"),
        )

    def test_subscription_lifecycle(self):
        # 1. Create
        sub = lifecycle.create_subscription(
            customer=self.customer,
            plan=self.plan,
            start_date=datetime.date(2026, 1, 1),
            user=self.staff,
        )
        self.assertEqual(sub.status, SubscriptionStatus.DRAFT)
        self.assertTrue(sub.number.startswith("SUB-"))

        # 2. To Quotation
        SubscriptionLine.objects.create(subscription=sub, product=self.product, quantity=1, unit_price=self.product.sales_price, tax_rate=Decimal('0.00'))
        sub = lifecycle.to_quotation(sub, actor=self.staff)
        self.assertEqual(sub.status, SubscriptionStatus.QUOTATION)

        # 3. Confirm
        sub = lifecycle.confirm(sub, actor=self.staff)
        self.assertEqual(sub.status, SubscriptionStatus.CONFIRMED)

        # 4. Activate
        sub = lifecycle.activate(sub, actor=self.staff)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE)

        # 5. Pause
        sub = lifecycle.pause(sub, actor=self.staff)
        self.assertTrue(sub.is_paused)

        # 6. Resume
        sub = lifecycle.resume(sub, actor=self.staff)
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE)

        # 7. Close
        sub = lifecycle.close(sub, actor=self.staff)
        self.assertEqual(sub.status, SubscriptionStatus.CLOSED)

    def test_quotation_template_creation_and_sub(self):
        tmpl = QuotationTemplate.objects.create(
            name="Starter Template",
            plan=self.plan,
            validity_days=15,
        )
        TemplateLine.objects.create(
            template=tmpl,
            product=self.product,
            quantity=2,
        )

        sub = lifecycle.create_from_template(
            template=tmpl,
            customer=self.customer,
            start_date=datetime.date(2026, 1, 1),
            user=self.staff,
        )
        self.assertEqual(sub.status, SubscriptionStatus.DRAFT)
        self.assertEqual(sub.lines.count(), 1)
        self.assertEqual(sub.lines.first().quantity, 2)

    def test_subscription_views_access(self):
        # Staff can access subscriptions list
        self.client.force_login(self.staff)
        resp = self.client.get("/subscriptions/")
        self.assertEqual(resp.status_code, 200)

        # Customer is denied subscriptions list (403)
        self.client.force_login(self.cust_user)
        resp = self.client.get("/subscriptions/")
        self.assertEqual(resp.status_code, 403)

    def test_subscription_create_with_template_prefill(self):
        tmpl = QuotationTemplate.objects.create(
            name="Enterprise Bundle",
            plan=self.plan,
            validity_days=30,
        )
        self.client.force_login(self.staff)
        resp = self.client.get(f"/subscriptions/new/?template={tmpl.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enterprise Bundle")

    def test_staff_create_view(self):
        # Customer forbidden (403)
        self.client.force_login(self.cust_user)
        resp = self.client.get("/staff/new/")
        self.assertEqual(resp.status_code, 403)

        # Staff forbidden (admin only) (403)
        self.client.force_login(self.staff)
        resp = self.client.get("/staff/new/")
        self.assertEqual(resp.status_code, 403)

        # Admin allowed (200)
        self.client.force_login(self.admin)
        resp = self.client.get("/staff/new/")
        self.assertEqual(resp.status_code, 200)

        # Admin POST creates new staff
        post_data = {
            "email": "newemployee@brightloop.test",
            "full_name": "New Employee",
            "role": "staff",
            "password1": "SecurePass987!",
            "password2": "SecurePass987!",
        }
        resp = self.client.post("/staff/new/", post_data)
        self.assertRedirects(resp, "/reports/")
        self.assertTrue(User.objects.filter(email="newemployee@brightloop.test").exists())

    def test_invoice_print_view(self):
        sub = lifecycle.create_subscription(
            customer=self.customer,
            plan=self.plan,
            start_date=datetime.date(2026, 1, 1),
            user=self.staff,
        )
        inv = Invoice.objects.create(
            number="INV-2026-TESTPRINT",
            subscription=sub,
            customer=self.customer,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 1, 31),
            invoice_date=datetime.date(2026, 1, 1),
            due_date=datetime.date(2026, 1, 15),
            status=InvoiceStatus.CONFIRMED,
            total=Decimal("100.00"),
        )

        # Staff can print
        self.client.force_login(self.staff)
        resp = self.client.get(f"/invoices/{inv.number}/print/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "INV-2026-TESTPRINT")

        # Invoice owner customer can print
        self.client.force_login(self.cust_user)
        resp = self.client.get(f"/invoices/{inv.number}/print/")
        self.assertEqual(resp.status_code, 200)

        # Another customer is forbidden (403)
        other_user = User.objects.create_user(email="other@test.com", password="Password123!", role="customer")
        Customer.objects.create(user=other_user, name="Other Corp")
        self.client.force_login(other_user)
        resp = self.client.get(f"/invoices/{inv.number}/print/")
        self.assertEqual(resp.status_code, 403)
