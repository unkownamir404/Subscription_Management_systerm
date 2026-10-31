from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import Customer
from apps.accounts.validators import BrightloopPasswordValidator

User = get_user_model()


class PasswordValidatorTests(TestCase):
    def setUp(self):
        self.validator = BrightloopPasswordValidator()

    def test_eight_characters_rejected(self):
        """Must be more than 8 chars (8 chars is rejected)."""
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("Aa1@5678")
        self.assertIn("more than 8 characters", str(ctx.exception))

    def test_missing_uppercase_rejected(self):
        """Missing uppercase letter is rejected."""
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("password@123")
        self.assertIn("uppercase letter", str(ctx.exception))

    def test_missing_lowercase_rejected(self):
        """Missing lowercase letter is rejected."""
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("PASSWORD@123")
        self.assertIn("lowercase letter", str(ctx.exception))

    def test_missing_special_character_rejected(self):
        """Missing special character is rejected."""
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("Password123")
        self.assertIn("special character", str(ctx.exception))

    def test_valid_password_accepted(self):
        """A valid password meeting all requirements is accepted."""
        try:
            self.validator.validate("Brightloop@2026")
        except ValidationError:
            self.fail("Validator unexpectedly raised ValidationError on valid password.")


class AuthFlowTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_signup_creates_user_and_customer_and_redirects(self):
        """Valid signup creates User with role=customer and Customer profile."""
        response = self.client.post(reverse("signup"), {
            "email": "jane@example.com",
            "name": "Jane Doe",
            "company": "Jane Co",
            "password": "ValidPassword@123",
            "password_confirm": "ValidPassword@123",
        })
        self.assertRedirects(response, "/portal/")

        user = User.objects.get(email="jane@example.com")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)

        customer = Customer.objects.get(user=user)
        self.assertEqual(customer.name, "Jane Doe")
        self.assertEqual(customer.company, "Jane Co")

        # Verify user is logged into session
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_case_insensitive_email_uniqueness_on_signup(self):
        """Alice@x.com and alice@x.com cannot both register."""
        User.objects.create_user(
            email="alice@x.com",
            password="ValidPassword@123",
            role=User.Role.CUSTOMER,
        )

        response = self.client.post(reverse("signup"), {
            "email": "Alice@X.com",
            "name": "Alice Duplicate",
            "company": "",
            "password": "ValidPassword@123",
            "password_confirm": "ValidPassword@123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "email",
            "An account with this email already exists.",
        )
        self.assertEqual(User.objects.filter(email__iexact="alice@x.com").count(), 1)

    def test_weak_password_rejected_on_signup(self):
        """Signup form rejects weak passwords."""
        response = self.client.post(reverse("signup"), {
            "email": "weak@example.com",
            "name": "Weak Pass User",
            "company": "",
            "password": "weak",
            "password_confirm": "weak",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(User.objects.filter(email="weak@example.com").exists())

    def test_password_mismatch_rejected(self):
        """Signup form rejects mismatched passwords."""
        response = self.client.post(reverse("signup"), {
            "email": "mismatch@example.com",
            "name": "Mismatch User",
            "company": "",
            "password": "ValidPassword@123",
            "password_confirm": "DifferentPassword@123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "password_confirm",
            "Passwords do not match.",
        )

    def test_case_insensitive_login(self):
        """User can log in case-insensitively."""
        user = User.objects.create_user(
            email="bob@example.com",
            password="ValidPassword@123",
            role=User.Role.CUSTOMER,
        )
        response = self.client.post(reverse("login"), {
            "username": "BOB@Example.com",
            "password": "ValidPassword@123",
        })
        self.assertRedirects(response, "/portal/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_password_reset_email_sent_for_registered_user(self):
        """Password reset email is sent to console/outbox for registered user."""
        User.objects.create_user(
            email="registered@brightloop.test",
            password="ValidPassword@123",
            role=User.Role.CUSTOMER,
        )
        response = self.client.post(reverse("password_reset"), {
            "email": "registered@brightloop.test",
        })
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["registered@brightloop.test"])
        self.assertIn("password-reset/", mail.outbox[0].body)

    def test_password_reset_unknown_email_leaks_nothing(self):
        """Password reset for unknown email returns same done redirect without sending email."""
        response = self.client.post(reverse("password_reset"), {
            "email": "nonexistent@brightloop.test",
        })
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)


class StaffNewAccessTests(TestCase):
    """Section 12: Only admin can create staff; staff and customers get 403."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@brightloop.test",
            password="Admin@12345",
            role=User.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.staff = User.objects.create_user(
            email="staff@brightloop.test",
            password="Staff@12345",
            role=User.Role.STAFF,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            email="cust@brightloop.test",
            password="Cust@12345",
            role=User.Role.CUSTOMER,
        )
        Customer.objects.create(user=self.customer, name="Test Customer")

    def test_admin_can_get_staff_new(self):
        """Admin receives 200 on GET /staff/new/."""
        self.client.force_login(self.admin)
        response = self.client.get(reverse("staff_new"))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_create_staff_user(self):
        """Admin can POST to /staff/new/ and create a staff user."""
        self.client.force_login(self.admin)
        response = self.client.post(reverse("staff_new"), {
            "email": "newstaff@brightloop.test",
            "name": "New Staff",
            "password": "StaffPass@123",
            "password_confirm": "StaffPass@123",
        })
        # Redirects on success
        self.assertIn(response.status_code, [200, 302])
        new_user = User.objects.get(email="newstaff@brightloop.test")
        self.assertEqual(new_user.role, User.Role.STAFF)
        self.assertTrue(new_user.is_staff)

    def test_staff_cannot_access_staff_new_returns_403(self):
        """Staff user receives 403 on GET /staff/new/."""
        self.client.force_login(self.staff)
        response = self.client.get(reverse("staff_new"))
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_post_staff_new_returns_403(self):
        """Staff user receives 403 on POST /staff/new/."""
        self.client.force_login(self.staff)
        response = self.client.post(reverse("staff_new"), {
            "email": "sneaky@brightloop.test",
            "name": "Sneaky",
            "password": "Sneaky@123",
            "password_confirm": "Sneaky@123",
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email="sneaky@brightloop.test").exists())

    def test_customer_cannot_access_staff_new_returns_403(self):
        """Customer receives 403 on GET /staff/new/."""
        self.client.force_login(self.customer)
        response = self.client.get(reverse("staff_new"))
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_redirected_from_staff_new(self):
        """Unauthenticated user is redirected to login from /staff/new/."""
        response = self.client.get(reverse("staff_new"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)


class CrossCustomer404Tests(TestCase):
    """
    Section 12: Cross-customer access returns 404; wrong role returns 403.
    Tests at the portal level (apps.portal.tests covers invoice/payment isolation).
    This class verifies the rule at the subscription level via the staff subscriptions view.
    """

    def setUp(self):
        from datetime import date, timedelta
        from decimal import Decimal
        from apps.catalog.models import Plan, Product, Tax
        from apps.subscriptions.models import Subscription

        self.admin = User.objects.create_user(
            email="admin2@brightloop.test",
            password="Admin@12345",
            role=User.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.customer_a = User.objects.create_user(
            email="custa@brightloop.test",
            password="Cust@12345",
            role=User.Role.CUSTOMER,
        )
        self.customer_b = User.objects.create_user(
            email="custb@brightloop.test",
            password="Cust@12345",
            role=User.Role.CUSTOMER,
        )
        self.cust_a_profile = Customer.objects.create(user=self.customer_a, name="Cust A")
        self.cust_b_profile = Customer.objects.create(user=self.customer_b, name="Cust B")

        self.tax = Tax.objects.create(name="GST", rate=Decimal("18"), is_default=True)
        self.plan = Plan.objects.create(
            name="Test Plan",
            price=Decimal("500"),
            interval=Plan.Interval.MONTHLY,
            interval_count=1,
            valid_from=date.today(),
        )
        self.sub_b = Subscription.objects.create(
            customer=self.cust_b_profile,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            start_date=date.today(),
            expiry_date=date.today() + timedelta(days=30),
            billing_anchor=date.today(),
        )

    def test_customer_accessing_another_subscription_via_portal_returns_404(self):
        """Customer A accessing Customer B's portal subscription detail gets 404."""
        self.client.force_login(self.customer_a)
        from apps.subscriptions.models import Subscription
        url = reverse("portal:subscription_detail", kwargs={"pk": self.sub_b.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_customer_accessing_admin_subscription_list_returns_403(self):
        """Customer accessing the staff/admin subscription list gets 403."""
        self.client.force_login(self.customer_a)
        response = self.client.get(reverse("subscriptions:subscription_list"))
        self.assertEqual(response.status_code, 403)
