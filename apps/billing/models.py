from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from apps.core.models import TimeStamped

class InvoiceStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    CONFIRMED = 'confirmed', 'Confirmed'
    PAID = 'paid', 'Paid'
    CANCELLED = 'cancelled', 'Cancelled'

class Invoice(TimeStamped):
    number = models.CharField(max_length=32, null=True, blank=True, unique=True)
    subscription = models.ForeignKey('subscriptions.Subscription', on_delete=models.PROTECT, related_name='invoices')
    customer = models.ForeignKey('accounts.Customer', on_delete=models.PROTECT, related_name='invoices')
    period_start = models.DateField()
    period_end = models.DateField()
    invoice_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['subscription', 'period_start'],
                name='unique_invoice_subscription_period_start',
            ),
            models.CheckConstraint(
                check=Q(amount_paid__lte=F('total')),
                name='invoice_amount_paid_lte_total',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'due_date'], name='inv_status_due_date_idx'),
            models.Index(fields=['customer'], name='inv_customer_idx'),
            models.Index(fields=['invoice_date'], name='inv_invoice_date_idx'),
        ]

    def __str__(self):
        return f"{self.number or 'DRAFT'} - {self.customer.name} ({self.total})"

class InvoiceLine(TimeStamped):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    description = models.CharField(max_length=255)
    product = models.ForeignKey('catalog.Product', on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.ForeignKey('catalog.Discount', on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.description} ({self.line_total})"

class DiscountRedemption(TimeStamped):
    discount = models.ForeignKey('catalog.Discount', on_delete=models.PROTECT, related_name='redemptions')
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='discount_redemptions')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['discount', 'invoice'],
                name='unique_discount_invoice_redemption',
            ),
        ]

    def __str__(self):
        return f"{self.discount.name} redeemed on {self.invoice.number or self.invoice.id}"

class PaymentMethod(models.TextChoices):
    BANK_TRANSFER = 'bank_transfer', 'Bank Transfer'
    CARD = 'card', 'Card'
    UPI = 'upi', 'UPI'
    CASH = 'cash', 'Cash'
    CHEQUE = 'cheque', 'Cheque'

class Payment(TimeStamped):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name='payment_amount_gt_0'),
        ]
        indexes = [
            models.Index(fields=['invoice'], name='payment_invoice_idx'),
        ]

    def __str__(self):
        return f"Payment {self.id} for Invoice {self.invoice.number or self.invoice.id} ({self.amount})"

class BillingItemResult(models.TextChoices):
    CREATED = 'created', 'Created'
    SKIPPED = 'skipped', 'Skipped'
    FAILED = 'failed', 'Failed'

class BillingRun(TimeStamped):
    run_date = models.DateField()
    as_of = models.DateField()
    dry_run = models.BooleanField(default=False)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Billing Run {self.id} ({self.run_date}) - {self.created_count} created"

class BillingRunItem(TimeStamped):
    run = models.ForeignKey(BillingRun, on_delete=models.CASCADE, related_name='items')
    subscription = models.ForeignKey('subscriptions.Subscription', on_delete=models.CASCADE)
    result = models.CharField(max_length=20, choices=BillingItemResult.choices)
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['run'], name='billing_run_item_run_idx'),
        ]

    def __str__(self):
        return f"Run {self.run.id} Sub {self.subscription.number}: {self.result}"

class ReminderStage(models.TextChoices):
    T_MINUS_3 = 't_minus_3', 'T-3'
    T_PLUS_1 = 't_plus_1', 'T+1'
    T_PLUS_7 = 't_plus_7', 'T+7'

class ReminderLog(TimeStamped):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='reminder_logs')
    stage = models.CharField(max_length=20, choices=ReminderStage.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['invoice', 'stage'], name='unique_invoice_reminder_stage'),
        ]

    def __str__(self):
        return f"Reminder {self.stage} for Invoice {self.invoice.number or self.invoice.id}"

class InvoiceCounter(TimeStamped):
    key = models.CharField(max_length=32, unique=True)
    last_value = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.key}: {self.last_value}"
