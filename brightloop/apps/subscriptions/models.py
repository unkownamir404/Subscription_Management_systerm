from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStamped
from apps.accounts.models import Customer
from apps.catalog.models import Plan, Product, ProductVariant


class SubscriptionQuerySet(models.QuerySet):
    def for_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_superuser or getattr(user, "role", None) in ("admin", "staff"):
            return self.all()
        return self.filter(customer__user=user)


class SubscriptionEventManager(models.Manager):
    def for_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_superuser or getattr(user, "role", None) in ("admin", "staff"):
            return self.all()
        return self.filter(subscription__customer__user=user)


class QuotationTemplate(TimeStamped):
    name = models.CharField(max_length=255)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="quotation_templates")
    validity_days = models.IntegerField(default=30, help_text="Number of days quotation remains valid")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.plan.name})"


class TemplateLine(TimeStamped):
    template = models.ForeignKey(QuotationTemplate, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="template_lines")
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.IntegerField(default=1)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"


class Subscription(TimeStamped):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUOTATION = "quotation", "Quotation"
        CONFIRMED = "confirmed", "Confirmed"
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"

    number = models.CharField(max_length=50, unique=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    start_date = models.DateField()
    expiry_date = models.DateField()
    payment_terms_days = models.IntegerField(default=15)
    quote_valid_until = models.DateField(null=True, blank=True)
    billing_anchor = models.DateField(null=True, blank=True)
    periods_billed = models.IntegerField(default=0)
    next_invoice_date = models.DateField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_subscriptions",
    )

    objects = SubscriptionQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "next_invoice_date"], name="idx_sub_status_next_inv"),
            models.Index(fields=["customer"], name="idx_sub_customer"),
            models.Index(fields=["expiry_date"], name="idx_sub_expiry"),
        ]

    def __str__(self):
        return f"{self.number or 'Draft'} - {self.customer}"

    def save(self, *args, **kwargs):
        if not self.number and self.pk:
            year = self.created_at.year if self.created_at else timezone.now().year
            self.number = f"SUB-{year}-{self.pk:06d}"
            kwargs["update_fields"] = list(set(kwargs.get("update_fields", [])) | {"number"})
        super().save(*args, **kwargs)
        if not self.number:
            year = self.created_at.year if self.created_at else timezone.now().year
            self.number = f"SUB-{year}-{self.pk:06d}"
            super().save(update_fields=["number"])


class SubscriptionLine(TimeStamped):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="subscription_lines")
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Snapshotted price at creation")
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"), help_text="Snapshotted tax rate")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="check_sub_line_qty_gte_1",
            )
        ]

    def __str__(self):
        return f"{self.product.name} (x{self.quantity}) @ ₹{self.unit_price}"

    @property
    def line_subtotal(self):
        return self.unit_price * self.quantity

    @property
    def line_tax(self):
        return (self.line_subtotal * self.tax_rate / Decimal("100.00")).quantize(Decimal("0.01"))

    @property
    def line_total(self):
        return self.line_subtotal + self.line_tax


class SubscriptionEvent(TimeStamped):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    action = models.CharField(max_length=50)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.TextField(blank=True)

    objects = SubscriptionEventManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["subscription", "created_at"], name="idx_sub_event_sub_created"),
        ]

    def __str__(self):
        return f"{self.subscription.number}: {self.from_status}->{self.to_status} ({self.action})"
