from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.billing.models import Invoice, Payment
from apps.billing.services.tax import round_money


def record_payment(
    invoice: Invoice,
    method: str,
    amount: Decimal,
    paid_on=None,
    note: str = "",
    user=None,
) -> Payment:
    """
    Records a payment against an invoice inside a database transaction with a row lock.
    """
    amount = round_money(amount)
    if amount <= Decimal("0.00"):
        raise ValidationError("Payment amount must be greater than zero.")

    with transaction.atomic():
        # Lock invoice row to prevent race conditions
        locked_invoice = Invoice.objects.select_for_update().get(id=invoice.id)

        if locked_invoice.status not in (Invoice.Status.CONFIRMED, Invoice.Status.DRAFT):
            raise ValidationError(f"Cannot record payment for invoice with status '{locked_invoice.status}'.")

        balance = locked_invoice.balance_due
        if amount > balance:
            raise ValidationError(
                f"Payment amount (₹{amount}) cannot exceed the outstanding balance (₹{balance})."
            )

        paid_date = paid_on or timezone.now().date()
        payment = Payment.objects.create(
            invoice=locked_invoice,
            method=method,
            amount=amount,
            paid_on=paid_date,
            note=note,
            recorded_by=user,
        )

        locked_invoice.amount_paid += amount
        if locked_invoice.amount_paid >= locked_invoice.total:
            locked_invoice.status = Invoice.Status.PAID
        elif locked_invoice.status == Invoice.Status.DRAFT:
            locked_invoice.status = Invoice.Status.CONFIRMED

        locked_invoice.save(update_fields=["amount_paid", "status", "updated_at"])

    return payment
