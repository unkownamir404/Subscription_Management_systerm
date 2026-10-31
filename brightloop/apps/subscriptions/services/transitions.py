from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.subscriptions.models import Subscription, SubscriptionEvent


def mark_as_quotation(subscription: Subscription, user=None, note: str = "") -> Subscription:
    if subscription.status != Subscription.Status.DRAFT:
        raise ValidationError(f"Cannot transition to quotation from status {subscription.status}.")

    with transaction.atomic():
        old_status = subscription.status
        subscription.status = Subscription.Status.QUOTATION
        if not subscription.quote_valid_until:
            valid_days = getattr(subscription.plan, "validity_days", 30)
            subscription.quote_valid_until = timezone.now().date() + timedelta(days=valid_days)
        subscription.save(update_fields=["status", "quote_valid_until", "updated_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=old_status,
            to_status=subscription.status,
            action="quotation",
            actor=user,
            note=note or "Quotation issued to customer.",
        )
    return subscription


def confirm_subscription(subscription: Subscription, user=None, note: str = "") -> Subscription:
    if subscription.status not in (Subscription.Status.DRAFT, Subscription.Status.QUOTATION):
        raise ValidationError(f"Cannot confirm subscription from status {subscription.status}.")

    # Expiry guard: quotation cannot be confirmed if quote_valid_until < today
    today = timezone.now().date()
    if subscription.status == Subscription.Status.QUOTATION and subscription.quote_valid_until:
        if subscription.quote_valid_until < today:
            raise ValidationError("Quotation has expired and cannot be confirmed.")

    with transaction.atomic():
        old_status = subscription.status
        subscription.status = Subscription.Status.CONFIRMED
        subscription.save(update_fields=["status", "updated_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=old_status,
            to_status=subscription.status,
            action="confirm",
            actor=user,
            note=note or "Subscription confirmed.",
        )
    return subscription


def activate_subscription(subscription: Subscription, user=None, note: str = "") -> Subscription:
    if subscription.status != Subscription.Status.CONFIRMED:
        raise ValidationError(f"Cannot activate subscription from status {subscription.status}.")

    with transaction.atomic():
        old_status = subscription.status
        subscription.status = Subscription.Status.ACTIVE
        subscription.billing_anchor = subscription.start_date
        subscription.periods_billed = 0
        subscription.next_invoice_date = subscription.start_date
        subscription.paused_at = None
        subscription.save(update_fields=[
            "status",
            "billing_anchor",
            "periods_billed",
            "next_invoice_date",
            "paused_at",
            "updated_at",
        ])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=old_status,
            to_status=subscription.status,
            action="activate",
            actor=user,
            note=note or "Subscription activated. Billing anchor established.",
        )
    return subscription


def pause_subscription(subscription: Subscription, user=None, note: str = "") -> Subscription:
    if subscription.status != Subscription.Status.ACTIVE:
        raise ValidationError(f"Cannot pause subscription in status {subscription.status}.")
    if subscription.paused_at is not None:
        raise ValidationError("Subscription is already paused.")

    if not subscription.plan.allow_pause:
        raise ValidationError("This subscription plan does not allow pausing.")

    with transaction.atomic():
        subscription.paused_at = timezone.now()
        subscription.save(update_fields=["paused_at", "updated_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=subscription.status,
            to_status=subscription.status,
            action="pause",
            actor=user,
            note=note or "Subscription paused.",
        )
    return subscription


def resume_subscription(subscription: Subscription, user=None, note: str = "") -> Subscription:
    if subscription.status != Subscription.Status.ACTIVE or subscription.paused_at is None:
        raise ValidationError("Subscription is not paused.")

    today = timezone.now().date()
    paused_days = max(1, (today - subscription.paused_at.date()).days)

    with transaction.atomic():
        subscription.expiry_date = subscription.expiry_date + timedelta(days=paused_days)
        subscription.billing_anchor = today
        subscription.periods_billed = 0
        subscription.next_invoice_date = today
        subscription.paused_at = None
        subscription.save(update_fields=[
            "expiry_date",
            "billing_anchor",
            "periods_billed",
            "next_invoice_date",
            "paused_at",
            "updated_at",
        ])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=subscription.status,
            to_status=subscription.status,
            action="resume",
            actor=user,
            note=note or f"Subscription resumed. Expiry extended by {paused_days} days.",
        )
    return subscription


def close_subscription(subscription: Subscription, user=None, note: str = "") -> Subscription:
    if subscription.status == Subscription.Status.CLOSED:
        raise ValidationError("Subscription is already closed.")

    today = timezone.now().date()
    if subscription.status == Subscription.Status.ACTIVE and subscription.expiry_date > today:
        if not subscription.plan.allow_early_close:
            raise ValidationError("This subscription plan does not allow early close.")

    with transaction.atomic():
        old_status = subscription.status
        subscription.status = Subscription.Status.CLOSED
        subscription.paused_at = None
        subscription.save(update_fields=["status", "paused_at", "updated_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=old_status,
            to_status=subscription.status,
            action="close",
            actor=user,
            note=note or "Subscription closed.",
        )
    return subscription


def renew_subscription(subscription: Subscription, user=None, note: str = "") -> Subscription:
    if not subscription.plan.allow_renew:
        raise ValidationError("This subscription plan does not allow renewal.")

    interval = subscription.plan.interval
    count = subscription.plan.interval_count
    interval_map = {
        "daily": relativedelta(days=count),
        "weekly": relativedelta(weeks=count),
        "monthly": relativedelta(months=count),
        "yearly": relativedelta(years=count),
    }
    delta = interval_map.get(interval, relativedelta(months=count))

    with transaction.atomic():
        old_status = subscription.status
        subscription.expiry_date = subscription.expiry_date + delta
        if subscription.status == Subscription.Status.CLOSED:
            subscription.status = Subscription.Status.ACTIVE
            subscription.billing_anchor = timezone.now().date()
            subscription.next_invoice_date = timezone.now().date()
            subscription.periods_billed = 0

        subscription.save(update_fields=[
            "expiry_date",
            "status",
            "billing_anchor",
            "next_invoice_date",
            "periods_billed",
            "updated_at",
        ])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            from_status=old_status,
            to_status=subscription.status,
            action="renew",
            actor=user,
            note=note or f"Subscription renewed until {subscription.expiry_date}.",
        )
    return subscription
