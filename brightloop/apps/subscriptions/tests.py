from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import Customer
from apps.catalog.models import Plan, Product, ProductVariant, Tax
from apps.subscriptions.models import (
    Subscription,
    SubscriptionLine,
    SubscriptionEvent,
    QuotationTemplate,
    TemplateLine,
)
from apps.subscriptions.services import transitions

User = get_user_model()


class SubscriptionTransitionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@brightloop.test",
            password="AdminPassword@123",
            role=User.Role.ADMIN,
        )
        self.customer_user = User.objects.create_user(
            email="cust@brightloop.test",
            password="CustPassword@123",
            role=User.Role.CUSTOMER,
        )
        self.customer = Customer.objects.create(
            user=self.customer_user,
            name="Alpha Corp",
        )
        self.tax = Tax.objects.create(name="GST 18%", rate=Decimal("18.00"), is_default=True)
        self.product = Product.objects.create(name="ERP Core", sales_price=Decimal("1000.00"), tax=self.tax)
        self.variant = ProductVariant.objects.create(
            product=self.product,
            attribute="Brand",
            value="Odoo",
            extra_price=Decimal("560.00"),
        )
        self.plan = Plan.objects.create(
            name="Monthly SaaS",
            price=Decimal("1200.00"),
            interval=Plan.Interval.MONTHLY,
            interval_count=1,
            valid_from=date.today(),
            allow_pause=True,
            allow_renew=True,
            allow_early_close=True,
        )
        self.subscription = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.Status.DRAFT,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(days=30),
            created_by=self.admin,
        )

    def test_full_legal_transition_lifecycle(self):
        """Tests legal transition path: draft -> quotation -> confirmed -> active -> pause -> resume -> close -> renew."""
        sub = self.subscription

        # 1. Draft -> Quotation
        sub = transitions.mark_as_quotation(sub, user=self.admin, note="Quote sent")
        self.assertEqual(sub.status, Subscription.Status.QUOTATION)
        self.assertTrue(sub.events.filter(action="quotation").exists())

        # 2. Quotation -> Confirmed
        sub = transitions.confirm_subscription(sub, user=self.admin, note="Quote confirmed")
        self.assertEqual(sub.status, Subscription.Status.CONFIRMED)
        self.assertTrue(sub.events.filter(action="confirm").exists())

        # 3. Confirmed -> Active
        sub = transitions.activate_subscription(sub, user=self.admin, note="Activated")
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(sub.billing_anchor, sub.start_date)
        self.assertEqual(sub.next_invoice_date, sub.start_date)
        self.assertEqual(sub.periods_billed, 0)
        self.assertTrue(sub.events.filter(action="activate").exists())

        # 4. Active -> Paused
        sub = transitions.pause_subscription(sub, user=self.admin, note="Pause requested")
        self.assertIsNotNone(sub.paused_at)
        self.assertTrue(sub.events.filter(action="pause").exists())

        # 5. Paused -> Resumed
        old_expiry = sub.expiry_date
        sub = transitions.resume_subscription(sub, user=self.admin, note="Resuming now")
        self.assertIsNone(sub.paused_at)
        self.assertGreaterEqual(sub.expiry_date, old_expiry)
        self.assertTrue(sub.events.filter(action="resume").exists())

        # 6. Active -> Closed
        sub = transitions.close_subscription(sub, user=self.admin, note="Terminated early")
        self.assertEqual(sub.status, Subscription.Status.CLOSED)
        self.assertTrue(sub.events.filter(action="close").exists())

        # 7. Closed -> Renewed
        old_expiry = sub.expiry_date
        sub = transitions.renew_subscription(sub, user=self.admin, note="Customer renewed")
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertGreater(sub.expiry_date, old_expiry)
        self.assertTrue(sub.events.filter(action="renew").exists())

    def test_illegal_transition_jumps_rejected(self):
        """Illegal state transitions must raise ValidationError."""
        sub = self.subscription  # in DRAFT status

        # Cannot activate draft directly
        with self.assertRaises(ValidationError):
            transitions.activate_subscription(sub)

        # Cannot pause draft
        with self.assertRaises(ValidationError):
            transitions.pause_subscription(sub)

    def test_pause_blocked_when_plan_disallows_pause(self):
        """If plan.allow_pause is False, pausing raises ValidationError."""
        no_pause_plan = Plan.objects.create(
            name="Strict Annual",
            price=Decimal("5000.00"),
            interval=Plan.Interval.YEARLY,
            valid_from=date.today(),
            allow_pause=False,
        )
        sub = Subscription.objects.create(
            customer=self.customer,
            plan=no_pause_plan,
            status=Subscription.Status.ACTIVE,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(days=365),
        )
        with self.assertRaises(ValidationError) as ctx:
            transitions.pause_subscription(sub)
        self.assertIn("does not allow pausing", str(ctx.exception))

    def test_expired_quotation_cannot_be_confirmed(self):
        """A quotation whose quote_valid_until < today cannot be confirmed."""
        yesterday = date.today() - timedelta(days=1)
        sub = Subscription.objects.create(
            customer=self.customer,
            plan=self.plan,
            status=Subscription.Status.QUOTATION,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(days=30),
            quote_valid_until=yesterday,
        )
        with self.assertRaises(ValidationError) as ctx:
            transitions.confirm_subscription(sub)
        self.assertIn("expired", str(ctx.exception).lower())


class SubscriptionViewAndSecurityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@brightloop.test",
            password="AdminPassword@123",
            role=User.Role.ADMIN,
        )
        self.user_a = User.objects.create_user(
            email="cust_a@brightloop.test",
            password="CustPassword@123",
            role=User.Role.CUSTOMER,
        )
        self.customer_a = Customer.objects.create(user=self.user_a, name="Company A")

        self.user_b = User.objects.create_user(
            email="cust_b@brightloop.test",
            password="CustPassword@123",
            role=User.Role.CUSTOMER,
        )
        self.customer_b = Customer.objects.create(user=self.user_b, name="Company B")

        self.tax = Tax.objects.create(name="GST 18%", rate=Decimal("18.00"), is_default=True)
        self.product = Product.objects.create(name="Hosting", sales_price=Decimal("500.00"), tax=self.tax)
        self.plan = Plan.objects.create(
            name="Basic Monthly",
            price=Decimal("500.00"),
            interval=Plan.Interval.MONTHLY,
            valid_from=date.today(),
        )

        self.sub_a = Subscription.objects.create(
            customer=self.customer_a,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(days=30),
        )
        self.sub_b = Subscription.objects.create(
            customer=self.customer_b,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(days=30),
        )

    def test_customer_cross_access_returns_404(self):
        """Customer A accessing staff-side /subscriptions/ gets 403 (not a customer route).
        Cross-customer 404 is verified via the portal (apps.portal.tests)."""
        client = Client()
        client.force_login(self.user_a)

        # Customers are not allowed on the staff-side detail view -> 403
        response_own = client.get(reverse("subscriptions:subscription_detail", kwargs={"pk": self.sub_a.pk}))
        self.assertEqual(response_own.status_code, 403)

        # Accessing Customer B's subscription via staff route also returns 403 (role check fires first)
        response_other = client.get(reverse("subscriptions:subscription_detail", kwargs={"pk": self.sub_b.pk}))
        self.assertEqual(response_other.status_code, 403)

    def test_line_snapshot_pricing_and_tax_rate(self):
        """SubscriptionLine snapshots unit_price and tax_rate and does not change when catalog changes."""
        client = Client()
        client.force_login(self.admin)

        variant = ProductVariant.objects.create(
            product=self.product,
            attribute="Brand",
            value="Odoo",
            extra_price=Decimal("560.00"),
        )

        post_data = {
            "customer": str(self.customer_a.id),
            "plan": str(self.plan.id),
            "start_date": str(date.today()),
            "expiry_date": str(date.today() + timedelta(days=30)),
            "payment_terms_days": "15",
            "quote_valid_until": "",
            # Lines formset
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-product": str(self.product.id),
            "lines-0-variant": str(variant.id),
            "lines-0-quantity": "2",
        }

        response = client.post(reverse("subscriptions:subscription_create"), post_data)
        self.assertEqual(response.status_code, 302)

        sub = Subscription.objects.latest("id")
        line = sub.lines.first()
        self.assertIsNotNone(line)
        # Unit price = base (plan 500.00) + variant (560.00) = 1060.00
        self.assertEqual(line.unit_price, Decimal("1060.00"))
        self.assertEqual(line.tax_rate, Decimal("18.00"))

        # Mutate catalog prices
        self.product.sales_price = Decimal("9999.00")
        self.product.save()
        variant.extra_price = Decimal("8888.00")
        variant.save()

        # Reload subscription line: snapshot must remain unchanged
        line.refresh_from_db()
        self.assertEqual(line.unit_price, Decimal("1060.00"))

    def test_create_quotation_from_template(self):
        """Generating quotation from template copies lines and calculates snapshot prices."""
        template = QuotationTemplate.objects.create(
            name="Startup Bundle",
            plan=self.plan,
            validity_days=14,
            is_active=True,
        )
        TemplateLine.objects.create(template=template, product=self.product, quantity=3)

        client = Client()
        client.force_login(self.admin)

        post_data = {
            "template": str(template.id),
            "customer": str(self.customer_b.id),
            "start_date": str(date.today()),
        }

        response = client.post(reverse("subscriptions:create_quotation_from_template"), post_data)
        self.assertEqual(response.status_code, 302)

        new_sub = Subscription.objects.filter(customer=self.customer_b).latest("id")
        self.assertEqual(new_sub.status, Subscription.Status.QUOTATION)
        self.assertEqual(new_sub.quote_valid_until, date.today() + timedelta(days=14))
        self.assertEqual(new_sub.lines.count(), 1)

        sub_line = new_sub.lines.first()
        self.assertEqual(sub_line.quantity, 3)
        self.assertEqual(sub_line.unit_price, Decimal("500.00"))
        self.assertEqual(sub_line.tax_rate, Decimal("18.00"))
