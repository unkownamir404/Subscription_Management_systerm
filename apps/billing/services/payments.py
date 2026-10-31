from datetime import date
from decimal import Decimal
from typing import Optional
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.billing.models import Invoice, InvoiceStatus, Payment


def record_payment(
    invoice: Invoice,
    method: str = "card",
    amount: Optional[Decimal] = None,
    paid_on: Optional[date] = None,
    note: str = "",
    user=None,
) -> Payment:
    """
    Records an invoice payment in a transaction per DESIGN.md section 5.6 and S4:
      - Row-locks the invoice row (select_for_update)
      - Enforces status 'confirmed'
      - Rejects amount <= 0 or amount > balance
      - Inserts the Payment record
      - Updates amount_paid and marks status 'paid' when settled.
    """
    with transaction.atomic():
        inv = Invoice.objects.select_for_update(of=("self",)).get(pk=invoice.pk)

        if inv.status != InvoiceStatus.CONFIRMED:
            raise DomainError(f"Cannot record payment for invoice with status '{inv.status}'. Must be 'confirmed'.")

        balance = inv.total - inv.amount_paid
        if amount is None:
            amount = balance
        elif not isinstance(amount, Decimal):
            amount = Decimal(str(amount))

        if amount <= Decimal("0.00"):
            raise DomainError("Payment amount must be greater than zero.")

        if amount > balance:
            raise DomainError(f"Overpayment rejected. Amount ({amount}) exceeds remaining balance ({balance}).")

        if paid_on is None:
            paid_on = timezone.localdate()

        payment = Payment.objects.create(
            invoice=inv,
            method=method,
            amount=amount,
            paid_on=paid_on,
            note=note,
            recorded_by=user if user and getattr(user, "is_authenticated", False) else None,
        )

        inv.amount_paid += amount
        update_fields = ["amount_paid", "updated_at"]
        if inv.amount_paid >= inv.total:
            inv.status = InvoiceStatus.PAID
            update_fields.append("status")
        inv.save(update_fields=update_fields)

    return payment
