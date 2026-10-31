from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.core.models import TimeStamped

class QuotationTemplate(TimeStamped):
    name = models.CharField(max_length=255)
    plan = models.ForeignKey('catalog.Plan', on_delete=models.PROTECT, related_name='templates')
    validity_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class TemplateLine(TimeStamped):
    template = models.ForeignKey(QuotationTemplate, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('catalog.Product', on_delete=models.PROTECT)
    variant = models.ForeignKey('catalog.ProductVariant', on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.template.name} - {self.product.name} x {self.quantity}"

class SubscriptionStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    QUOTATION = 'quotation', 'Quotation'
    CONFIRMED = 'confirmed', 'Confirmed'
    ACTIVE = 'active', 'Active'
    CLOSED = 'closed', 'Closed'

class Subscription(TimeStamped):
    number = models.CharField(max_length=32, unique=True)
    customer = models.ForeignKey('accounts.Customer', on_delete=models.PROTECT, related_name='subscriptions')
    plan = models.ForeignKey('catalog.Plan', on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=SubscriptionStatus.choices, default=SubscriptionStatus.DRAFT)
    start_date = models.DateField()
    expiry_date = models.DateField()
    payment_terms_days = models.PositiveIntegerField(default=15)
    quote_valid_until = models.DateField(null=True, blank=True)
    billing_anchor = models.DateField(null=True, blank=True)
    periods_billed = models.PositiveIntegerField(default=0)
    next_invoice_date = models.DateField(null=True, blank=True)
    paused_at = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_subscriptions')

    class Meta:
        indexes = [
            models.Index(fields=['status', 'next_invoice_date'], name='sub_status_next_inv_idx'),
            models.Index(fields=['customer'], name='sub_customer_idx'),
            models.Index(fields=['expiry_date'], name='sub_expiry_date_idx'),
        ]

    def __str__(self):
        return f"{self.number} ({self.customer.name})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.number and is_new:
            import time
            self.number = f"SUB-TEMP-{int(time.time() * 1000)}"
        super().save(*args, **kwargs)
        if is_new and (not self.number or self.number.startswith("SUB-TEMP-")):
            from django.utils import timezone
            year = (self.created_at or timezone.now()).year
            self.number = f"SUB-{year}-{self.pk:06d}"
            super().save(update_fields=['number'])

    @property
    def is_paused(self) -> bool:
        return self.paused_at is not None

    def is_expired(self, today=None) -> bool:
        if today is None:
            from django.utils import timezone
            today = timezone.localdate()
        return self.expiry_date < today

    def is_quote_expired(self, today=None) -> bool:
        if today is None:
            from django.utils import timezone
            today = timezone.localdate()
        return bool(self.quote_valid_until and self.quote_valid_until < today)

class SubscriptionLine(TimeStamped):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('catalog.Product', on_delete=models.PROTECT)
    variant = models.ForeignKey('catalog.ProductVariant', on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        constraints = [
            models.CheckConstraint(check=Q(quantity__gte=1), name='sub_line_qty_gte_1'),
        ]

    def __str__(self):
        return f"{self.subscription.number} - {self.product.name} x {self.quantity}"

class SubscriptionEvent(TimeStamped):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='events')
    from_status = models.CharField(max_length=32)
    to_status = models.CharField(max_length=32)
    action = models.CharField(max_length=64)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['subscription', 'created_at'], name='sub_event_sub_created_idx'),
        ]

    def __str__(self):
        return f"{self.subscription.number}: {self.from_status} -> {self.to_status} ({self.action})"
