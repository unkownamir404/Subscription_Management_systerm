from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import Customer
from apps.billing.models import Invoice, InvoiceLine, Payment
from apps.catalog.models import Plan, Product, Tax
from apps.subscriptions.models import Subscription, SubscriptionLine

User = get_user_model()


class CustomerPortalTests(TestCase):
    def setUp(self):
        # Staff user
        self.staff_user = User.objects.create_user(
            email="staff@brightloop.test",
            password="StaffPassword@123",
            role=User.Role.STAFF,
            is_staff=True,
        )

        # Customer A
        self.user_a = User.objects.create_user(
            email="alice@brightloop.test",
            password="CustPassword@123",
            role=User.Role.CUSTOMER,
        )
        self.customer_a = Customer.objects.create(user=self.user_a, name="Alice Corp")

        # Customer B
        self.user_b = User.objects.create_user(
            email="bob@brightloop.test",
            password="CustPassword@123",
            role=User.Role.CUSTOMER,
        )
        self.customer_b = Customer.objects.create(user=self.user_b, name="Bob Enterprises")

        # Plan & Product
        self.tax = Tax.objects.create(name="GST 18%", rate=Decimal("18.00"), is_default=True)
        self.product = Product.objects.create(name="Cloud Platform", sales_price=Decimal("1000.00"), tax=self.tax)
        self.plan = Plan.objects.create(
            name="Monthly Cloud",
            price=Decimal("1000.00"),
            interval=Plan.Interval.MONTHLY,
            interval_count=1,
            valid_from=date.today(),
            allow_pause=True,
            allow_renew=True,
        )

        # Subscriptions
        self.sub_a = Subscription.objects.create(
            customer=self.customer_a,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(days=30),
            next_invoice_date=date.today() + timedelta(days=30),
            billing_anchor=date.today(),
        )
        SubscriptionLine.objects.create(
            subscription=self.sub_a,
            product=self.product,
            quantity=1,
            unit_price=Decimal("1000.00"),
            tax_rate=Decimal("18.00"),
        )

        self.sub_b = Subscription.objects.create(
            customer=self.customer_b,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(days=30),
            next_invoice_date=date.today() + timedelta(days=30),
            billing_anchor=date.today(),
        )

        # Invoices
        self.invoice_a = Invoice.objects.create(
            number="INV-2026-000001",
            subscription=self.sub_a,
            customer=self.customer_a,
            period_start=date.today(),
            period_end=date.today() + timedelta(days=29),
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=15),
            status=Invoice.Status.CONFIRMED,
            subtotal=Decimal("1000.00"),
            tax_total=Decimal("180.00"),
            total=Decimal("1180.00"),
            amount_paid=Decimal("0.00"),
        )
        InvoiceLine.objects.create(
            invoice=self.invoice_a,
            description="Cloud Platform",
            product=self.product,
            quantity=1,
            unit_price=Decimal("1000.00"),
            tax_rate=Decimal("18.00"),
            tax_amount=Decimal("180.00"),
            line_total=Decimal("1180.00"),
        )

        self.invoice_b = Invoice.objects.create(
            number="INV-2026-000002",
            subscription=self.sub_b,
            customer=self.customer_b,
            period_start=date.today(),
            period_end=date.today() + timedelta(days=29),
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=15),
            status=Invoice.Status.CONFIRMED,
            subtotal=Decimal("2000.00"),
            tax_total=Decimal("360.00"),
            total=Decimal("2360.00"),
            amount_paid=Decimal("0.00"),
        )

    def test_staff_user_is_redirected_away_from_portal(self):
        """Staff users visiting /portal/ are redirected away."""
        client = Client()
        client.force_login(self.staff_user)

        response = client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/subscriptions/"))

    def test_customer_cannot_see_another_customer_invoice_returns_404(self):
        """Customer A accessing Customer B's invoice receives 404."""
        client = Client()
        client.force_login(self.user_a)

        # Access own invoice -> 200
        response_own = client.get(reverse("portal:invoice_detail", kwargs={"pk": self.invoice_a.pk}))
        self.assertEqual(response_own.status_code, 200)

        # Access other customer's invoice -> 404
        response_other = client.get(reverse("portal:invoice_detail", kwargs={"pk": self.invoice_b.pk}))
        self.assertEqual(response_other.status_code, 404)

    def test_customer_cannot_pay_another_customer_invoice_returns_404(self):
        """Customer A attempting to pay Customer B's invoice receives 404."""
        client = Client()
        client.force_login(self.user_a)

        # Attempt to GET or POST checkout on Customer B's invoice -> 404
        get_response = client.get(reverse("portal:pay_invoice", kwargs={"pk": self.invoice_b.pk}))
        self.assertEqual(get_response.status_code, 404)

        post_response = client.post(reverse("portal:pay_invoice", kwargs={"pk": self.invoice_b.pk}))
        self.assertEqual(post_response.status_code, 404)

        # Invoice B balance untouched
        self.invoice_b.refresh_from_db()
        self.assertEqual(self.invoice_b.amount_paid, Decimal("0.00"))
        self.assertEqual(self.invoice_b.status, Invoice.Status.CONFIRMED)

    def test_customer_can_pay_own_invoice_with_card(self):
        """Customer A can pay own invoice via mock card payment; status changes to Paid."""
        client = Client()
        client.force_login(self.user_a)

        response = client.post(reverse("portal:pay_invoice", kwargs={"pk": self.invoice_a.pk}))
        self.assertEqual(response.status_code, 302)

        self.invoice_a.refresh_from_db()
        self.assertEqual(self.invoice_a.amount_paid, Decimal("1180.00"))
        self.assertEqual(self.invoice_a.status, Invoice.Status.PAID)

        # Payment record created with method=card
        payment = self.invoice_a.payments.first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.method, Payment.Method.CARD)
        self.assertEqual(payment.amount, Decimal("1180.00"))

    def test_next_invoice_preview_on_portal(self):
        """Next-invoice preview renders on dashboard without writing to the database."""
        client = Client()
        client.force_login(self.user_a)

        initial_invoice_count = Invoice.objects.count()

        response = client.get(reverse("portal:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["next_invoice_preview"])
        self.assertEqual(response.context["next_invoice_preview"].total, Decimal("1180.00"))

        # Zero invoices written to DB
        self.assertEqual(Invoice.objects.count(), initial_invoice_count)

    def test_customer_self_service_pause_and_renew(self):
        """Customer can pause and renew own subscription within plan permissions."""
        client = Client()
        client.force_login(self.user_a)

        # Pause
        pause_resp = client.post(
            reverse("portal:subscription_action", kwargs={"pk": self.sub_a.pk, "action": "pause"})
        )
        self.assertEqual(pause_resp.status_code, 302)
        self.sub_a.refresh_from_db()
        self.assertIsNotNone(self.sub_a.paused_at)

        # Resume
        resume_resp = client.post(
            reverse("portal:subscription_action", kwargs={"pk": self.sub_a.pk, "action": "resume"})
        )
        self.assertEqual(resume_resp.status_code, 302)
        self.sub_a.refresh_from_db()
        self.assertIsNone(self.sub_a.paused_at)

        # Renew
        old_expiry = self.sub_a.expiry_date
        renew_resp = client.post(
            reverse("portal:subscription_action", kwargs={"pk": self.sub_a.pk, "action": "renew"})
        )
        self.assertEqual(renew_resp.status_code, 302)
        self.sub_a.refresh_from_db()
        self.assertGreater(self.sub_a.expiry_date, old_expiry)
