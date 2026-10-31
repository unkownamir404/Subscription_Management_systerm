from decimal import Decimal
from django.test import TestCase
from apps.billing.services.pricing import line_unit_price
from apps.catalog.models import Plan, Product, ProductType, ProductVariant


class PricingServiceTests(TestCase):
    def setUp(self):
        self.primary_product = Product.objects.create(
            name="ERP Core",
            product_type=ProductType.SOFTWARE,
            sales_price=Decimal("1200.00"),
        )
        self.addon_product = Product.objects.create(
            name="Storage Addon",
            product_type=ProductType.ADDON,
            sales_price=Decimal("250.00"),
        )
        self.odoo_variant = ProductVariant.objects.create(
            product=self.primary_product,
            attribute="Brand",
            value="Odoo",
            extra_price=Decimal("560.00"),
        )
        self.plan = Plan.objects.create(
            name="Standard Plan",
            price=Decimal("1000.00"),
            interval="monthly",
            valid_from="2026-01-01",
        )

    def test_odoo_variant_plus_560_example(self):
        """DESIGN.md §5.1: The Odoo brand variant adds 560 to plan price."""
        unit_price = line_unit_price(
            product=self.primary_product,
            variant=self.odoo_variant,
            plan_or_none=self.plan,
        )
        # base = 1000.00, extra = 560.00 -> 1560.00
        self.assertEqual(unit_price, Decimal("1560.00"))

    def test_table_driven_pricing_scenarios(self):
        cases = [
            ("Primary line with variant", self.primary_product, self.odoo_variant, self.plan, Decimal("1560.00")),
            ("Primary line without variant", self.primary_product, None, self.plan, Decimal("1000.00")),
            ("Add-on line without variant", self.addon_product, None, None, Decimal("250.00")),
            ("Add-on line with variant", self.addon_product, self.odoo_variant, None, Decimal("810.00")),
        ]

        for desc, prod, variant, plan, expected in cases:
            with self.subTest(scenario=desc):
                price = line_unit_price(prod, variant, plan)
                self.assertEqual(price, expected)
