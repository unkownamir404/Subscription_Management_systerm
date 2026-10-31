from decimal import Decimal
from django.db import models
from django.db.models import F, Q
from apps.core.models import TimeStamped

class Tax(TimeStamped):
    name = models.CharField(max_length=100)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    is_default = models.BooleanField(default=False)
    priority = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(rate__gte=0) & Q(rate__lte=100),
                name='tax_rate_between_0_and_100',
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.rate}%)"

class ProductType(models.TextChoices):
    SERVICE = 'service', 'Service'
    SOFTWARE = 'software', 'Software'
    ADDON = 'addon', 'Addon'
    OTHER = 'other', 'Other'

class Product(TimeStamped):
    name = models.CharField(max_length=255)
    product_type = models.CharField(max_length=20, choices=ProductType.choices, default=ProductType.SERVICE)
    sales_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True)
    tax = models.ForeignKey(Tax, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=Q(sales_price__gte=0), name='product_sales_price_gte_0'),
            models.CheckConstraint(check=Q(cost_price__gte=0), name='product_cost_price_gte_0'),
        ]

    def __str__(self):
        return self.name

class ProductVariant(TimeStamped):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    attribute = models.CharField(max_length=100)
    value = models.CharField(max_length=100)
    extra_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'attribute', 'value'],
                name='unique_product_variant',
            ),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.attribute}: {self.value} (+{self.extra_price})"

class PlanInterval(models.TextChoices):
    DAILY = 'daily', 'Daily'
    WEEKLY = 'weekly', 'Weekly'
    MONTHLY = 'monthly', 'Monthly'
    YEARLY = 'yearly', 'Yearly'

class Plan(TimeStamped):
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    interval = models.CharField(max_length=20, choices=PlanInterval.choices, default=PlanInterval.MONTHLY)
    interval_count = models.PositiveIntegerField(default=1)
    min_qty = models.PositiveIntegerField(default=1)
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    auto_close = models.BooleanField(default=False)
    allow_early_close = models.BooleanField(default=False)
    allow_pause = models.BooleanField(default=False)
    allow_renew = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(valid_to__isnull=True) | Q(valid_to__gte=F('valid_from')),
                name='plan_valid_to_gte_valid_from',
            ),
            models.CheckConstraint(check=Q(min_qty__gte=1), name='plan_min_qty_gte_1'),
        ]

    def __str__(self):
        return f"{self.name} ({self.price} / {self.interval_count} {self.interval})"

class DiscountKind(models.TextChoices):
    FIXED = 'fixed', 'Fixed'
    PERCENT = 'percent', 'Percent'

class DiscountScope(models.TextChoices):
    PRODUCTS = 'products', 'Products'
    SUBSCRIPTION = 'subscription', 'Subscription'

class Discount(TimeStamped):
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=DiscountKind.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    min_qty = models.PositiveIntegerField(default=0)
    start_date = models.DateField()
    end_date = models.DateField()
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0)
    scope = models.CharField(max_length=20, choices=DiscountScope.choices, default=DiscountScope.SUBSCRIPTION)
    products = models.ManyToManyField(Product, blank=True, related_name='discounts')
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(usage_limit__isnull=True) | Q(used_count__lte=F('usage_limit')),
                name='discount_used_count_lte_limit',
            ),
            models.CheckConstraint(
                check=Q(end_date__gte=F('start_date')),
                name='discount_end_date_gte_start_date',
            ),
            models.CheckConstraint(
                check=~Q(kind='percent') | Q(value__lte=100),
                name='discount_percent_lte_100',
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.kind}: {self.value})"
