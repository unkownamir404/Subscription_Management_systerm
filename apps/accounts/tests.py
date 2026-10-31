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



class CustomerManagementViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff = User.objects.create_user(
            email="staff_cust@brightloop.test", password="ValidPassword@123", role="staff", is_staff=True
        )
        self.cust_user = User.objects.create_user(
            email="client@brightloop.test", password="ValidPassword@123", role="customer"
        )
        self.customer = Customer.objects.create(
            user=self.cust_user,
            name="Alpha Corp",
            company="Alpha Technologies",
            phone="9876543210",
            tax_id="GSTIN12345",
        )

    def test_customer_list_access_staff(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/customers/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alpha Corp")

    def test_customer_list_denied_customer(self):
        self.client.force_login(self.cust_user)
        resp = self.client.get("/customers/")
        self.assertEqual(resp.status_code, 403)

    def test_customer_detail_view(self):
        self.client.force_login(self.staff)
        resp = self.client.get(f"/customers/{self.customer.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alpha Corp")
        self.assertContains(resp, "GSTIN12345")

    def test_customer_update_view(self):
        self.client.force_login(self.staff)
        resp = self.client.post(f"/customers/{self.customer.id}/edit/", {
            "name": "Alpha Corp Updated",
            "company": "Alpha Global Inc",
            "phone": "9998887776",
            "tax_id": "GSTIN99999",
            "billing_address": "456 Tech Park",
        })
        self.assertRedirects(resp, f"/customers/{self.customer.id}/")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, "Alpha Corp Updated")
        self.assertEqual(self.customer.company, "Alpha Global Inc")
