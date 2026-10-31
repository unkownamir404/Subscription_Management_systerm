from decimal import Decimal
from django.db import models
from django.db.models import F, Q
from apps.core.models import TimeStamped


class Tax(TimeStamped):
    name = models.CharField(max_length=100)
    rate = models.DecimalField(max_digits=5, decimal_places=2, help_text="Tax percentage (0-100)")
    is_default = models.BooleanField(default=False)
    priority = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural = "Taxes"
        ordering = ["-is_default", "priority", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(rate__gte=0, rate__lte=100),
                name="check_tax_rate_range",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class Product(TimeStamped):
    class ProductType(models.TextChoices):
        SERVICE = "service", "Service"
        SOFTWARE = "software", "Software"
        ADDON = "addon", "Add-on"
        OTHER = "other", "Other"

    name = models.CharField(max_length=255)
    product_type = models.CharField(
        max_length=50,
        choices=ProductType.choices,
        default=ProductType.SOFTWARE,
    )
    sales_price = models.DecimalField(max_digits=12, decimal_places=2)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    tax = models.ForeignKey(
        Tax,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(sales_price__gte=0) & Q(cost_price__gte=0),
                name="check_product_prices_non_negative",
            )
        ]

    def __str__(self):
        return self.name


class ProductVariant(TimeStamped):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
    )
    attribute = models.CharField(max_length=100, help_text='e.g. "Brand"')
    value = models.CharField(max_length=100, help_text='e.g. "Odoo"')
    extra_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Additional price for this variant (e.g. 560.00)",
    )

    class Meta:
        ordering = ["attribute", "value"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "attribute", "value"],
                name="unique_product_variant",
            )
        ]

    def __str__(self):
        return f"{self.product.name} - {self.attribute}: {self.value} (+₹{self.extra_price})"


class Plan(TimeStamped):
    class Interval(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    interval = models.CharField(
        max_length=20,
        choices=Interval.choices,
        default=Interval.MONTHLY,
    )
    interval_count = models.IntegerField(default=1)
    min_qty = models.IntegerField(default=1)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)

    # Lifecycle flags
    auto_close = models.BooleanField(default=True)
    allow_early_close = models.BooleanField(default=True)
    allow_pause = models.BooleanField(default=True)
    allow_renew = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")),
                name="check_plan_valid_dates",
            ),
            models.CheckConstraint(
                condition=Q(min_qty__gte=1),
                name="check_plan_min_qty",
            ),
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name="check_plan_price_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.name} (₹{self.price} / {self.interval_count} {self.interval})"


class Discount(TimeStamped):
    class Kind(models.TextChoices):
        FIXED = "fixed", "Fixed Amount"
        PERCENT = "percent", "Percentage"

    class Scope(models.TextChoices):
        PRODUCTS = "products", "Specific Products"
        SUBSCRIPTION = "subscription", "Whole Subscription"

    name = models.CharField(max_length=255)
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.PERCENT,
    )
    value = models.DecimalField(max_digits=12, decimal_places=2)
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    min_qty = models.IntegerField(default=0)
    start_date = models.DateField()
    end_date = models.DateField()
    usage_limit = models.IntegerField(null=True, blank=True)
    used_count = models.IntegerField(default=0)
    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        default=Scope.SUBSCRIPTION,
    )
    products = models.ManyToManyField(Product, blank=True, related_name="discounts")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_date", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")),
                name="check_discount_dates",
            ),
            models.CheckConstraint(
                condition=Q(usage_limit__isnull=True) | Q(used_count__lte=F("usage_limit")),
                name="check_discount_used_count",
            ),
            models.CheckConstraint(
                condition=~Q(kind="percent") | Q(value__lte=100),
                name="check_discount_percent_max",
            ),
        ]

    def __str__(self):
        suffix = "%" if self.kind == self.Kind.PERCENT else "₹"
        return f"{self.name} ({self.value}{suffix})"


# Top-level enum aliases matching DESIGN.md and test suites
ProductType = Product.ProductType
PlanInterval = Plan.Interval
DiscountKind = Discount.Kind
DiscountScope = Discount.Scope
