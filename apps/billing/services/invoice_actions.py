from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceCounter, InvoiceStatus, Payment, PaymentMethod


@transaction.atomic
def confirm_invoice(invoice: Invoice, user=None) -> Invoice:
    """
    Confirms a draft invoice and assigns a gapless invoice number
    INV-<year>-<6 digits> from InvoiceCounter under a row lock.
    """
    inv = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if inv.status != InvoiceStatus.DRAFT:
        raise ValidationError(
            f"Only draft invoices can be confirmed. Current status: '{inv.status}'."
        )

    year = inv.invoice_date.year if inv.invoice_date else timezone.localdate().year
    counter_key = f"INV-{year}"

    counter, _ = InvoiceCounter.objects.select_for_update().get_or_create(
        key=counter_key,
        defaults={'last_value': 0}
    )
    counter.last_value += 1
    counter.save(update_fields=['last_value', 'updated_at'])

    inv.number = f"{counter_key}-{counter.last_value:06d}"
    inv.status = InvoiceStatus.CONFIRMED
    inv.save(update_fields=['number', 'status', 'updated_at'])

    invoice.number = inv.number
    invoice.status = inv.status
    invoice.updated_at = inv.updated_at
    return inv


@transaction.atomic
def cancel_invoice(invoice: Invoice, user=None) -> Invoice:
    """
    Cancels a draft or confirmed invoice only when amount_paid == 0.
    The cancelled invoice keeps its period.
    """
    inv = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if inv.status not in (InvoiceStatus.DRAFT, InvoiceStatus.CONFIRMED):
        raise ValidationError(
            f"Only draft or confirmed invoices can be cancelled. Current status: '{inv.status}'."
        )

    if inv.amount_paid and inv.amount_paid > Decimal('0.00'):
        raise ValidationError(
            f"Cannot cancel an invoice with payments recorded (amount_paid = {inv.amount_paid})."
        )

    inv.status = InvoiceStatus.CANCELLED
    inv.save(update_fields=['status', 'updated_at'])

    invoice.status = inv.status
    invoice.updated_at = inv.updated_at
    return inv


def mark_sent(invoice: Invoice) -> Invoice:
    """
    Sets sent_at timestamp on the invoice without modifying status.
    """
    invoice.sent_at = timezone.now()
    invoice.save(update_fields=['sent_at', 'updated_at'])
    return invoice


@transaction.atomic
def record_payment(
    invoice: Invoice,
    method: str,
    amount: Decimal,
    paid_on=None,
    note: str = "",
    user=None,
) -> Payment:
    """
    Per DESIGN.md section 5.6:
    Lock the invoice row, require status confirmed, reject amount <= 0 or amount > balance,
    insert the payment, update amount_paid, set paid when settled.
    """
    inv = Invoice.objects.select_for_update().get(pk=invoice.pk)

    if inv.status != InvoiceStatus.CONFIRMED:
        if inv.status == InvoiceStatus.DRAFT:
            raise ValidationError("Payments cannot be recorded on draft invoices.")
        elif inv.status == InvoiceStatus.PAID:
            raise ValidationError("Invoice is already fully paid.")
        elif inv.status == InvoiceStatus.CANCELLED:
            raise ValidationError("Payments cannot be recorded on cancelled invoices.")
        else:
            raise ValidationError(
                f"Payments require confirmed status. Current status: '{inv.status}'."
            )

    if isinstance(amount, float):
        raise TypeError("Payment amount must be a Decimal or string, not float.")

    try:
        amount = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception as e:
        raise ValidationError(f"Invalid payment amount: {e}")

    if amount <= Decimal('0.00'):
        raise ValidationError("Payment amount must be greater than zero.")

    balance = (inv.total - inv.amount_paid).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if amount > balance:
        raise ValidationError(
            f"Payment amount ({amount}) exceeds remaining balance ({balance})."
        )

    if method not in PaymentMethod.values:
        raise ValidationError(
            f"Invalid payment method '{method}'. Valid choices: {list(PaymentMethod.values)}."
        )

    if paid_on is None:
        paid_on = timezone.localdate()

    payment = Payment.objects.create(
        invoice=inv,
        method=method,
        amount=amount,
        paid_on=paid_on,
        note=note or "",
        recorded_by=user,
    )

    inv.amount_paid = (inv.amount_paid + amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    update_fields = ['amount_paid', 'updated_at']

    if inv.amount_paid >= inv.total:
        inv.status = InvoiceStatus.PAID
        update_fields.append('status')

    inv.save(update_fields=update_fields)

    invoice.amount_paid = inv.amount_paid
    invoice.status = inv.status
    invoice.updated_at = inv.updated_at

    return payment
