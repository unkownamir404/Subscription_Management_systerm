from decimal import Decimal
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from apps.catalog.models import Product, ProductVariant, Plan, Tax, Discount

User = get_user_model()


class CatalogPermissionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@brightloop.test",
            password="AdminPassword@123",
            role=User.Role.ADMIN,
        )
        self.staff = User.objects.create_user(
            email="staff@brightloop.test",
            password="StaffPassword@123",
            role=User.Role.STAFF,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            email="customer@brightloop.test",
            password="CustomerPassword@123",
            role=User.Role.CUSTOMER,
        )

        self.tax = Tax.objects.create(name="GST 18%", rate=Decimal("18.00"), is_default=True)
        self.product = Product.objects.create(
            name="Business Suite",
            sales_price=Decimal("1200.00"),
            tax=self.tax,
        )
        self.plan = Plan.objects.create(
            name="Monthly Pro",
            price=Decimal("1200.00"),
            interval=Plan.Interval.MONTHLY,
            valid_from=date.today(),
        )

    def test_customer_gets_403_on_catalog(self):
        """Customers must receive 403 on all catalog pages."""
        client = Client()
        client.force_login(self.customer)

        urls = [
            reverse("catalog:product_list"),
            reverse("catalog:product_create"),
            reverse("catalog:plan_list"),
            reverse("catalog:plan_create"),
            reverse("catalog:tax_list"),
            reverse("catalog:discount_list"),
        ]
        for url in urls:
            response = client.get(url)
            self.assertEqual(response.status_code, 403, f"Expected 403 on {url} for customer")

    def test_staff_can_view_but_cannot_write(self):
        """Staff can view catalog lists, but gets 403 on create/edit views and POSTs."""
        client = Client()
        client.force_login(self.staff)

        # Staff can view lists
        response = client.get(reverse("catalog:product_list"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_write"])

        response = client.get(reverse("catalog:plan_list"))
        self.assertEqual(response.status_code, 200)

        # Staff gets 403 attempting to open create views
        self.assertEqual(client.get(reverse("catalog:product_create")).status_code, 403)
        self.assertEqual(client.get(reverse("catalog:plan_create")).status_code, 403)

        # Staff gets 403 attempting to POST create
        post_response = client.post(reverse("catalog:product_create"), {
            "name": "Hacked Product",
            "sales_price": "500.00",
            "cost_price": "0.00",
            "product_type": "software",
        })
        self.assertEqual(post_response.status_code, 403)

    def test_admin_can_write_product_with_variants(self):
        """Admin can create product with inline variant (e.g. Odoo brand +560)."""
        client = Client()
        client.force_login(self.admin)

        post_data = {
            "name": "ERP Software",
            "product_type": Product.ProductType.SOFTWARE,
            "sales_price": "1000.00",
            "cost_price": "200.00",
            "notes": "Main ERP suite",
            "tax": str(self.tax.id),
            "is_active": "on",
            # Formset management fields
            "variants-TOTAL_FORMS": "2",
            "variants-INITIAL_FORMS": "0",
            "variants-MIN_NUM_FORMS": "0",
            "variants-MAX_NUM_FORMS": "1000",
            # Variant 1: Brand Odoo +560
            "variants-0-attribute": "Brand",
            "variants-0-value": "Odoo",
            "variants-0-extra_price": "560.00",
            # Variant 2 (empty)
            "variants-1-attribute": "",
            "variants-1-value": "",
            "variants-1-extra_price": "",
        }

        response = client.post(reverse("catalog:product_create"), post_data)
        self.assertRedirects(response, reverse("catalog:product_list"))

        product = Product.objects.get(name="ERP Software")
        self.assertEqual(product.sales_price, Decimal("1000.00"))

        variant = product.variants.get(attribute="Brand", value="Odoo")
        self.assertEqual(variant.extra_price, Decimal("560.00"))


class CatalogValidationTests(TestCase):
    def test_product_negative_price_rejected(self):
        """Negative product prices are rejected."""
        from apps.catalog.forms import ProductForm
        form = ProductForm(data={
            "name": "Invalid Price Product",
            "product_type": Product.ProductType.SOFTWARE,
            "sales_price": "-10.00",
            "cost_price": "0.00",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("sales_price", form.errors)

    def test_plan_validation_edges(self):
        """Plan price >= 0, min_qty >= 1, valid_to >= valid_from."""
        from apps.catalog.forms import PlanForm
        today = date.today()

        # Negative price
        form = PlanForm(data={
            "name": "Test Plan",
            "price": "-50.00",
            "interval": Plan.Interval.MONTHLY,
            "interval_count": 1,
            "min_qty": 1,
            "valid_from": today,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("price", form.errors)

        # Min qty < 1
        form = PlanForm(data={
            "name": "Test Plan",
            "price": "100.00",
            "interval": Plan.Interval.MONTHLY,
            "interval_count": 1,
            "min_qty": 0,
            "valid_from": today,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("min_qty", form.errors)

        # valid_to < valid_from
        form = PlanForm(data={
            "name": "Test Plan",
            "price": "100.00",
            "interval": Plan.Interval.MONTHLY,
            "interval_count": 1,
            "min_qty": 1,
            "valid_from": today,
            "valid_to": today - timedelta(days=1),
        })
        self.assertFalse(form.is_valid())
        self.assertIn("valid_to", form.errors)

    def test_discount_validation_edges(self):
        """Discount percent <= 100, end_date >= start_date."""
        from apps.catalog.forms import DiscountForm
        today = date.today()

        # Percent > 100
        form = DiscountForm(data={
            "name": "Super Discount",
            "kind": Discount.Kind.PERCENT,
            "value": "110.00",
            "min_amount": "0.00",
            "min_qty": 0,
            "start_date": today,
            "end_date": today + timedelta(days=30),
            "scope": Discount.Scope.SUBSCRIPTION,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("value", form.errors)

        # End date < start date
        form = DiscountForm(data={
            "name": "Time Travel Discount",
            "kind": Discount.Kind.PERCENT,
            "value": "10.00",
            "min_amount": "0.00",
            "min_qty": 0,
            "start_date": today,
            "end_date": today - timedelta(days=5),
            "scope": Discount.Scope.SUBSCRIPTION,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("end_date", form.errors)
