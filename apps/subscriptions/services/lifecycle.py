from datetime import date, timedelta
from typing import Optional
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.core.periods import add_interval
from apps.subscriptions.models import (
    Subscription,
    SubscriptionEvent,
    SubscriptionLine,
    SubscriptionStatus,
    QuotationTemplate,
)


def create_subscription(
    customer,
    plan,
    start_date: date,
    expiry_date: Optional[date] = None,
    payment_terms_days: int = 15,
    user=None,
    status: str = SubscriptionStatus.DRAFT,
) -> Subscription:
    """
    Creates a new subscription in draft status.
    """
    if expiry_date is None:
        expiry_date = add_interval(start_date, plan.interval, plan.interval_count, 1)

    with transaction.atomic():
        sub = Subscription.objects.create(
            customer=customer,
            plan=plan,
            status=status,
            start_date=start_date,
            expiry_date=expiry_date,
            payment_terms_days=payment_terms_days,
            created_by=user,
        )
        SubscriptionEvent.objects.create(
            subscription=sub,
            from_status="",
            to_status=sub.status,
            action="create",
            actor=user,
            note="Subscription created",
        )
    return sub


def create_from_template(
    template: QuotationTemplate,
    customer,
    start_date: date,
    user=None,
) -> Subscription:
    """
    Creates a draft subscription populated with lines from a QuotationTemplate.
    """
    plan = template.plan
    expiry_date = add_interval(start_date, plan.interval, plan.interval_count, 1)

    with transaction.atomic():
        sub = Subscription.objects.create(
            customer=customer,
            plan=plan,
            status=SubscriptionStatus.DRAFT,
            start_date=start_date,
            expiry_date=expiry_date,
            created_by=user,
        )

        for line in template.lines.select_related("product", "variant"):
            extra = line.variant.extra_price if line.variant else 0
            unit_price = line.product.sales_price + extra
            tax_rate = line.product.tax.rate if line.product.tax else 0
            SubscriptionLine.objects.create(
                subscription=sub,
                product=line.product,
                variant=line.variant,
                quantity=line.quantity,
                unit_price=unit_price,
                tax_rate=tax_rate,
            )

        SubscriptionEvent.objects.create(
            subscription=sub,
            from_status="",
            to_status=sub.status,
            action="create",
            actor=user,
            note=f"Created from template: {template.name}",
        )
    return sub


def to_quotation(subscription: Subscription, actor=None, validity_days: int = 30, today: Optional[date] = None) -> Subscription:
    """
    Transitions draft -> quotation.
    Requires at least 1 line.
    Sets quote_valid_until = today + validity_days.
    """
    if subscription.status != SubscriptionStatus.DRAFT:
        raise DomainError(f"Cannot convert subscription in '{subscription.status}' status to quotation.")

    if not subscription.lines.exists():
        raise DomainError("Quotation must have at least one product line.")

    if today is None:
        today = timezone.localdate()

    with transaction.atomic():
        from_status = subscription.status
        subscription.status = SubscriptionStatus.QUOTATION
        subscription.quote_valid_until = today + timedelta(days=validity_days)
        subscription.save(update_fields=["status", "quote_valid_until", "updated_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=from_status,
            to_status=SubscriptionStatus.QUOTATION,
            action="to_quotation",
            actor=actor,
            note=f"Quotation valid until {subscription.quote_valid_until}",
        )
    return subscription


def confirm(subscription: Subscription, actor=None, today: Optional[date] = None) -> Subscription:
    """
    Transitions quotation -> confirmed.
    Conditions:
      - quote_valid_until is null or >= today
      - plan available on today (valid_from <= today <= valid_to)
      - every line quantity >= plan.min_qty
    """
    if subscription.status != SubscriptionStatus.QUOTATION:
        raise DomainError(f"Cannot confirm subscription in '{subscription.status}' status.")

    if today is None:
        today = timezone.localdate()

    if subscription.quote_valid_until and subscription.quote_valid_until < today:
        raise DomainError("Quotation has expired and cannot be confirmed.")

    plan = subscription.plan
    if plan.valid_from and plan.valid_from > today:
        raise DomainError(f"Plan '{plan.name}' is not yet valid.")
    if plan.valid_to and plan.valid_to < today:
        raise DomainError(f"Plan '{plan.name}' has expired.")

    for line in subscription.lines.all():
        if line.quantity < plan.min_qty:
            raise DomainError(f"Line '{line.product.name}' quantity ({line.quantity}) is less than plan minimum ({plan.min_qty}).")

    with transaction.atomic():
        from_status = subscription.status
        subscription.status = SubscriptionStatus.CONFIRMED
        subscription.save(update_fields=["status", "updated_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=from_status,
            to_status=SubscriptionStatus.CONFIRMED,
            action="confirm",
            actor=actor,
            note="Quotation confirmed",
        )
    return subscription


def activate(subscription: Subscription, actor=None) -> Subscription:
    """
    Activate a confirmed or draft subscription.
    Sets status=ACTIVE, billing_anchor=start_date, periods_billed=0, next_invoice_date=start_date.
    Logs a SubscriptionEvent.
    """
    if subscription.status not in (SubscriptionStatus.CONFIRMED, SubscriptionStatus.DRAFT, SubscriptionStatus.QUOTATION):
        if subscription.status == SubscriptionStatus.ACTIVE:
            return subscription
        raise DomainError(f"Cannot activate subscription in '{subscription.status}' status.")

    with transaction.atomic():
        from_status = subscription.status
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.billing_anchor = subscription.start_date
        subscription.periods_billed = 0
        subscription.next_invoice_date = subscription.start_date
        subscription.save(update_fields=[
            "status",
            "billing_anchor",
            "periods_billed",
            "next_invoice_date",
            "updated_at",
        ])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=from_status,
            to_status=SubscriptionStatus.ACTIVE,
            action="activate",
            actor=actor,
            note="Subscription activated",
        )
    return subscription


def pause(subscription: Subscription, actor=None, today: Optional[date] = None) -> Subscription:
    """
    Pauses an active subscription (only if plan.allow_pause and not already paused).
    Sets paused_at = today.
    """
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise DomainError("Only active subscriptions can be paused.")

    if subscription.is_paused:
        raise DomainError("Subscription is already paused.")

    if not subscription.plan.allow_pause:
        raise DomainError("This subscription plan does not allow pausing.")

    if today is None:
        today = timezone.localdate()

    with transaction.atomic():
        from_status = subscription.status
        subscription.paused_at = today
        subscription.save(update_fields=["paused_at", "updated_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=from_status,
            to_status=subscription.status,
            action="pause",
            actor=actor,
            note=f"Subscription paused as of {today}",
        )
    return subscription


def resume(subscription: Subscription, actor=None, today: Optional[date] = None) -> Subscription:
    """
    Resumes a paused active subscription:
      - clears paused_at
      - expiry_date += paused days
      - re-anchor: billing_anchor=today, periods_billed=0, next_invoice_date=today
    """
    if not subscription.is_paused:
        raise DomainError("Subscription is not paused.")

    if today is None:
        today = timezone.localdate()

    with transaction.atomic():
        paused_days = (today - subscription.paused_at).days if subscription.paused_at else 0
        if paused_days > 0:
            subscription.expiry_date = subscription.expiry_date + timedelta(days=paused_days)

        subscription.paused_at = None
        subscription.billing_anchor = today
        subscription.periods_billed = 0
        subscription.next_invoice_date = today
        subscription.save(update_fields=[
            "paused_at",
            "expiry_date",
            "billing_anchor",
            "periods_billed",
            "next_invoice_date",
            "updated_at",
        ])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=SubscriptionStatus.ACTIVE,
            to_status=SubscriptionStatus.ACTIVE,
            action="resume",
            actor=actor,
            note=f"Subscription resumed (extended by {paused_days} days)",
        )
    return subscription


def renew(subscription: Subscription, actor=None) -> Subscription:
    """
    Renews an active subscription (only if plan.allow_renew):
      - extends expiry_date by one plan term
    """
    if not subscription.plan.allow_renew:
        raise DomainError("This subscription plan does not permit renewals.")

    plan = subscription.plan
    with transaction.atomic():
        old_expiry = subscription.expiry_date
        subscription.expiry_date = add_interval(old_expiry, plan.interval, plan.interval_count, 1)
        subscription.save(update_fields=["expiry_date", "updated_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=subscription.status,
            to_status=subscription.status,
            action="renew",
            actor=actor,
            note=f"Renewed: expiry extended from {old_expiry} to {subscription.expiry_date}",
        )
    return subscription


def close(subscription: Subscription, actor=None) -> Subscription:
    """
    Early close of an active subscription (only if plan.allow_early_close):
      - status = CLOSED
      - clears next_invoice_date
    """
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise DomainError("Only active subscriptions can be closed.")

    if not subscription.plan.allow_early_close:
        raise DomainError("This subscription plan does not allow early closure.")

    with transaction.atomic():
        from_status = subscription.status
        subscription.status = SubscriptionStatus.CLOSED
        subscription.next_invoice_date = None
        subscription.save(update_fields=["status", "next_invoice_date", "updated_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=from_status,
            to_status=SubscriptionStatus.CLOSED,
            action="close",
            actor=actor,
            note="Subscription closed early",
        )
    return subscription


def auto_close_expired(today: Optional[date] = None) -> int:
    """
    Lifecycle job: closes active subscriptions where expiry_date < today and plan.auto_close=True.
    Returns count of subscriptions closed.
    """
    if today is None:
        today = timezone.localdate()

    candidates = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        expiry_date__lt=today,
        plan__auto_close=True,
    )
    count = 0
    for sub in candidates:
        with transaction.atomic():
            sub.status = SubscriptionStatus.CLOSED
            sub.next_invoice_date = None
            sub.save(update_fields=["status", "next_invoice_date", "updated_at"])

            SubscriptionEvent.objects.create(
                subscription=sub,
                from_status=SubscriptionStatus.ACTIVE,
                to_status=SubscriptionStatus.CLOSED,
                action="auto_close",
                actor=None,
                note="Auto-closed on expiration",
            )
            count += 1
    return count
