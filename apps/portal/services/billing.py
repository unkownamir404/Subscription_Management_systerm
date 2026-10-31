from datetime import date, timedelta
from decimal import Decimal
import sys
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.billing.models import Invoice, Payment, InvoiceStatus
from apps.billing.services.invoicing import build_invoice_draft
from apps.subscriptions.models import Subscription, SubscriptionStatus, SubscriptionEvent


@transaction.atomic
def record_payment(invoice, method="card", amount=None, paid_on=None, note="", user=None):
    """
    Records an invoice payment in a transaction per DESIGN.md section 5.6:
      - Row-locks the invoice (select_for_update)
      - Enforces status 'confirmed'
      - Rejects amount <= 0 or amount > balance
      - Inserts the Payment record
      - Updates amount_paid and automatically marks status 'paid' when settled.
    """
    # Row lock invoice
    inv = Invoice.objects.select_for_update().get(pk=invoice.pk)

    if inv.status != InvoiceStatus.CONFIRMED:
        raise ValueError(f"Cannot record payment for invoice with status '{inv.status}'. Must be 'confirmed'.")

    balance = inv.total - inv.amount_paid
    if amount is None:
        amount = balance
    elif not isinstance(amount, Decimal):
        amount = Decimal(str(amount))

    if amount <= Decimal("0.00"):
        raise ValueError("Payment amount must be greater than zero.")

    if amount > balance:
        raise ValueError(f"Overpayment rejected. Amount ({amount}) exceeds remaining balance ({balance}).")

    if paid_on is None:
        paid_on = timezone.localdate()

    actor = user if getattr(user, "is_authenticated", False) else None

    payment = Payment.objects.create(
        invoice=inv,
        method=method,
        amount=amount,
        paid_on=paid_on,
        note=note or f"Payment recorded via Customer Portal ({method})",
        recorded_by=actor,
    )

    inv.amount_paid += amount
    if inv.amount_paid >= inv.total:
        inv.status = InvoiceStatus.PAID
    inv.save(update_fields=["amount_paid", "status", "updated_at"])

    return payment


# Expose record_payment to apps.billing.services dynamically
import apps.billing.services as billing_services  # noqa: E402
setattr(billing_services, "record_payment", record_payment)
if "apps.billing.services" in sys.modules:
    setattr(sys.modules["apps.billing.services"], "record_payment", record_payment)


def get_next_invoice_preview(subscription):
    """
    Generates a pure next-invoice preview using build_invoice_draft (no DB writes).
    Returns None if subscription is not active or has expired.
    """
    if subscription.status != SubscriptionStatus.ACTIVE:
        return None

    target_date = subscription.next_invoice_date or subscription.start_date
    if not target_date or (subscription.expiry_date and target_date > subscription.expiry_date):
        return None

    try:
        draft = build_invoice_draft(subscription, target_date)
        return draft
    except Exception:
        return None


def pause_subscription(subscription, user=None):
    """
    Pauses an active subscription if plan allows pause.
    Sets paused_at to today and logs a SubscriptionEvent.
    """
    if not subscription.plan.allow_pause:
        raise ValueError("This plan does not permit pausing.")

    if subscription.status != SubscriptionStatus.ACTIVE:
        raise ValueError("Only active subscriptions can be paused.")

    if subscription.paused_at is not None:
        return subscription  # already paused

    today = timezone.localdate()
    subscription.paused_at = today
    subscription.save(update_fields=["paused_at", "updated_at"])

    SubscriptionEvent.objects.create(
        subscription=subscription,
        from_status=SubscriptionStatus.ACTIVE,
        to_status=SubscriptionStatus.ACTIVE,
        action="pause",
        actor=user if getattr(user, "is_authenticated", False) else None,
        note=f"Subscription paused by customer on {today}",
    )
    return subscription


def resume_subscription(subscription, user=None):
    """
    Resumes a paused subscription per DESIGN.md section 5.2:
      expiry_date += paused days, billing_anchor = today,
      periods_billed = 0, next_invoice_date = today, paused_at = None.
    """
    if subscription.paused_at is None:
        return subscription

    today = timezone.localdate()
    paused_days = max(0, (today - subscription.paused_at).days)

    subscription.expiry_date = subscription.expiry_date + timedelta(days=paused_days)
    subscription.billing_anchor = today
    subscription.periods_billed = 0
    subscription.next_invoice_date = today
    subscription.paused_at = None
    subscription.save(update_fields=[
        "expiry_date", "billing_anchor", "periods_billed",
        "next_invoice_date", "paused_at", "updated_at"
    ])

    SubscriptionEvent.objects.create(
        subscription=subscription,
        from_status=SubscriptionStatus.ACTIVE,
        to_status=SubscriptionStatus.ACTIVE,
        action="resume",
        actor=user if getattr(user, "is_authenticated", False) else None,
        note=f"Subscription resumed by customer on {today} after {paused_days} days paused",
    )
    return subscription


def renew_subscription(subscription, user=None):
    """
    Renews an active or closed subscription if plan allows renew.
    Extends expiry_date by one plan term and logs an event.
    """
    if not subscription.plan.allow_renew:
        raise ValueError("This plan does not permit self-service renewal.")

    plan = subscription.plan
    interval = getattr(plan, "interval", "monthly")
    count = getattr(plan, "interval_count", 1) or 1

    if interval == "daily":
        delta = relativedelta(days=count)
    elif interval == "weekly":
        delta = relativedelta(weeks=count)
    elif interval == "yearly":
        delta = relativedelta(years=count)
    else:
        delta = relativedelta(months=count)

    old_expiry = subscription.expiry_date
    new_expiry = old_expiry + delta

    from_status = subscription.status
    if subscription.status == SubscriptionStatus.CLOSED:
        subscription.status = SubscriptionStatus.ACTIVE

    subscription.expiry_date = new_expiry
    subscription.save(update_fields=["expiry_date", "status", "updated_at"])

    SubscriptionEvent.objects.create(
        subscription=subscription,
        from_status=from_status,
        to_status=subscription.status,
        action="renew",
        actor=user if getattr(user, "is_authenticated", False) else None,
        note=f"Subscription renewed from {old_expiry} to {new_expiry}",
    )
    return subscription
