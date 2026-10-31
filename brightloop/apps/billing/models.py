from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import TimeStamped
from apps.accounts.models import Customer
from apps.catalog.models import Discount, Product
from apps.subscriptions.models import Subscription


class InvoiceQuerySet(models.QuerySet):
    def for_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_superuser or getattr(user, "role", None) in ("admin", "staff"):
            return self.all()
        return self.filter(customer__user=user)


class PaymentManager(models.Manager):
    def for_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_superuser or getattr(user, "role", None) in ("admin", "staff"):
            return self.all()
        return self.filter(invoice__customer__user=user)


class Invoice(TimeStamped):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=50, null=True, blank=True, unique=True)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="invoices")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="invoices")
    period_start = models.DateField()
    period_end = models.DateField()
    invoice_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sent_at = models.DateTimeField(null=True, blank=True)

    objects = InvoiceQuerySet.as_manager()

    class Meta:
        ordering = ["-invoice_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "period_start"],
                name="unique_invoice_subscription_period",
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__lte=F("total")),
                name="check_invoice_amount_paid_lte_total",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "due_date"], name="idx_inv_status_due"),
            models.Index(fields=["customer"], name="idx_inv_customer"),
            models.Index(fields=["invoice_date"], name="idx_inv_date"),
        ]

    def __str__(self):
        return f"{self.number or 'Draft Invoice'} - {self.customer} (₹{self.total})"

    @property
    def balance_due(self):
        return max(Decimal("0.00"), self.total - self.amount_paid)

    @property
    def is_overdue(self):
        return self.status == self.Status.CONFIRMED and self.due_date < timezone.now().date()


class InvoiceLine(TimeStamped):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=255)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.ForeignKey(Discount, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.description} (x{self.quantity}) - ₹{self.line_total}"


class DiscountRedemption(TimeStamped):
    discount = models.ForeignKey(Discount, on_delete=models.CASCADE, related_name="redemptions")
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="discount_redemptions")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["discount", "invoice"],
                name="unique_discount_invoice_redemption",
            )
        ]

    def __str__(self):
        return f"{self.discount.name} redeemed on {self.invoice.number}"


class Payment(TimeStamped):
    class Method(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        CARD = "card", "Card"
        UPI = "upi", "UPI"
        CASH = "cash", "Cash"
        CHEQUE = "cheque", "Cheque"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=30, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField(default=timezone.now)
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    objects = PaymentManager()

    class Meta:
        ordering = ["-paid_on", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="check_payment_amount_positive",
            )
        ]
        indexes = [
            models.Index(fields=["invoice"], name="idx_payment_invoice"),
        ]

    def __str__(self):
        return f"Payment ₹{self.amount} ({self.get_method_display()}) for {self.invoice.number or self.invoice.id}"


class BillingRun(TimeStamped):
    run_date = models.DateField(auto_now_add=True)
    as_of = models.DateField()
    dry_run = models.BooleanField(default=False)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_count = models.IntegerField(default=0)
    skipped_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        mode = "Dry Run" if self.dry_run else "Committed"
        return f"Billing Run {self.id} ({mode}) - {self.run_date}: Created {self.created_count}, Skipped {self.skipped_count}"


class BillingRunItem(TimeStamped):
    class Result(models.TextChoices):
        CREATED = "created", "Created"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    run = models.ForeignKey(BillingRun, on_delete=models.CASCADE, related_name="items")
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    result = models.CharField(max_length=20, choices=Result.choices)
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["run"], name="idx_billing_run_item_run"),
        ]


class ReminderLog(TimeStamped):
    class Stage(models.TextChoices):
        T_MINUS_3 = "t_minus_3", "T-3 Days"
        T_PLUS_1 = "t_plus_1", "T+1 Day"
        T_PLUS_7 = "t_plus_7", "T+7 Days"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="reminders")
    stage = models.CharField(max_length=20, choices=Stage.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "stage"],
                name="unique_reminder_invoice_stage",
            )
        ]


class InvoiceCounter(models.Model):
    key = models.CharField(max_length=50, unique=True)
    last_value = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.key}: {self.last_value}"
