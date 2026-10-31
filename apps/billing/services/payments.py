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

        recipient = getattr(getattr(inv.customer, "user", None), "email", None)
        if recipient:
            def _send_payment_receipt(email=recipient, inv_num=(inv.number or str(inv.id)), amt=amount, stat=inv.status, meth=payment.get_method_display(), dt=paid_on):
                try:
                    from django.core.mail import send_mail
                    send_mail(
                        subject=f"Brightloop Payment Confirmation: Invoice #{inv_num}",
                        message=(
                            f"Hello {inv.customer.name},\n\n"
                            f"We have received your payment of ₹ {amt} via {meth} on {dt}.\n"
                            f"Invoice #{inv_num} status is now: {stat.upper()}.\n\n"
                            f"Thank you for your business,\nBrightloop Team"
                        ),
                        from_email=None,
                        recipient_list=[email],
                        fail_silently=True,
                    )
                except Exception:
                    pass
            transaction.on_commit(_send_payment_receipt)

    return payment
