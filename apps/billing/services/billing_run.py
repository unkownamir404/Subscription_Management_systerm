from datetime import date
from decimal import Decimal
from typing import Optional
from dateutil.relativedelta import relativedelta
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import (
    BillingItemResult,
    BillingRun,
    BillingRunItem,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
)
from apps.billing.services.discounts import redeem
from apps.billing.services.invoicing import build_invoice_draft
from apps.subscriptions.models import Subscription, SubscriptionStatus


def compute_period_start(anchor: date, n: int, interval: str, interval_count: int = 1) -> date:
    """
    Compute period_start(n) = anchor + n * interval_count * interval using relativedelta.
    Never uses repeated addition to prevent calendar drift.
    """
    count = max(1, interval_count)
    total_units = n * count
    if interval == 'daily':
        delta = relativedelta(days=total_units)
    elif interval == 'weekly':
        delta = relativedelta(weeks=total_units)
    elif interval == 'monthly':
        delta = relativedelta(months=total_units)
    elif interval == 'yearly':
        delta = relativedelta(years=total_units)
    else:
        delta = relativedelta(months=total_units)

    return anchor + delta


def run_billing(
    as_of: Optional[date] = None,
    dry_run: bool = False,
    user: Optional[object] = None,
) -> BillingRun:
    """
    Billing engine matching DESIGN.md §6:
    1. Select active, non-paused subscriptions due as of target date in chunks of 200.
    2. Each subscription runs in its own transaction with select_for_update(skip_locked=True).
    3. Loop while next_invoice_date <= as_of and next_invoice_date <= expiry_date (catch-up).
    4. Build draft, create Invoice & lines, redeem discounts, advance pointer.
    5. IntegrityError on (subscription, period_start) counts as skipped and advances pointer.
    6. Any other exception rolls back that subscription only and records failed BillingRunItem.
    7. dry_run writes nothing and returns an in-memory BillingRun result.
    """
    if as_of is None:
        as_of = timezone.localdate()
    run_date = timezone.localdate()

    if dry_run:
        billing_run = BillingRun(
            run_date=run_date,
            as_of=as_of,
            dry_run=True,
            started_by=user,
            created_count=0,
            skipped_count=0,
            failed_count=0,
        )
    else:
        billing_run = BillingRun.objects.create(
            run_date=run_date,
            as_of=as_of,
            dry_run=False,
            started_by=user,
            created_count=0,
            skipped_count=0,
            failed_count=0,
        )

    # 1. Query: active, non-paused, next_invoice_date <= as_of
    candidate_sub_ids = list(
        Subscription.objects.filter(
            status=SubscriptionStatus.ACTIVE,
            paused_at__isnull=True,
            next_invoice_date__isnull=False,
            next_invoice_date__lte=as_of,
        )
        .order_by('id')
        .values_list('id', flat=True)
    )

    chunk_size = 200
    for chunk_start in range(0, len(candidate_sub_ids), chunk_size):
        chunk_ids = candidate_sub_ids[chunk_start : chunk_start + chunk_size]

        for sub_id in chunk_ids:
            if dry_run:
                _process_subscription_dry_run(sub_id, as_of, billing_run)
            else:
                _process_subscription_live(sub_id, as_of, billing_run)

    billing_run.finished_at = timezone.now()
    if not dry_run:
        billing_run.save(update_fields=[
            'created_count',
            'skipped_count',
            'failed_count',
            'finished_at',
            'updated_at',
        ])

    return billing_run


def _process_subscription_dry_run(sub_id: int, as_of: date, billing_run: BillingRun) -> None:
    """Simulate invoice generation without writing to database."""
    sub = (
        Subscription.objects.select_related('plan', 'customer')
        .prefetch_related('lines__product', 'lines__variant')
        .filter(id=sub_id)
        .first()
    )
    if not sub:
        return

    if (
        sub.status != SubscriptionStatus.ACTIVE
        or sub.paused_at is not None
        or sub.next_invoice_date is None
        or sub.next_invoice_date > as_of
    ):
        return

    anchor = sub.billing_anchor or sub.start_date
    periods_billed = sub.periods_billed
    plan = sub.plan

    curr_start = compute_period_start(anchor, periods_billed, plan.interval, plan.interval_count)
    while curr_start <= as_of and curr_start <= sub.expiry_date:
        already_exists = Invoice.objects.filter(subscription=sub, period_start=curr_start).exists()
        if already_exists:
            billing_run.skipped_count += 1
        else:
            build_invoice_draft(sub, curr_start)
            billing_run.created_count += 1

        periods_billed += 1
        curr_start = compute_period_start(anchor, periods_billed, plan.interval, plan.interval_count)


def _process_subscription_live(sub_id: int, as_of: date, billing_run: BillingRun) -> None:
    """Process a single subscription in its own transaction with row lock."""
    try:
        with transaction.atomic():
            locked_sub = (
                Subscription.objects.select_for_update(skip_locked=True)
                .select_related('plan', 'customer')
                .prefetch_related('lines__product', 'lines__variant')
                .filter(id=sub_id)
                .first()
            )

            # Skip if locked by concurrent worker or deleted
            if not locked_sub:
                return

            # Re-check eligibility after acquiring the lock
            if (
                locked_sub.status != SubscriptionStatus.ACTIVE
                or locked_sub.paused_at is not None
                or locked_sub.next_invoice_date is None
                or locked_sub.next_invoice_date > as_of
            ):
                return

            anchor = locked_sub.billing_anchor or locked_sub.start_date
            plan = locked_sub.plan

            # Catch-up loop for any missed periods
            while locked_sub.next_invoice_date <= as_of and locked_sub.next_invoice_date <= locked_sub.expiry_date:
                period_start = locked_sub.next_invoice_date
                draft = build_invoice_draft(locked_sub, period_start)

                # Nested savepoint to catch IntegrityError on (subscription, period_start)
                try:
                    with transaction.atomic():
                        inv = Invoice.objects.create(
                            subscription=locked_sub,
                            customer=locked_sub.customer,
                            period_start=draft.period_start,
                            period_end=draft.period_end,
                            invoice_date=draft.invoice_date,
                            due_date=draft.due_date,
                            status=InvoiceStatus.DRAFT,
                            subtotal=draft.subtotal,
                            discount_total=draft.discount_total,
                            tax_total=draft.tax_total,
                            total=draft.total,
                            amount_paid=Decimal('0.00'),
                        )

                        for ld in draft.lines:
                            InvoiceLine.objects.create(
                                invoice=inv,
                                description=ld.description,
                                product=ld.product,
                                quantity=ld.quantity,
                                unit_price=ld.unit_price,
                                discount_amount=ld.discount_amount,
                                tax_rate=ld.tax_rate,
                                tax_amount=ld.tax_amount,
                                line_total=ld.line_total,
                                discount=ld.discount,
                            )

                        # Redeem distinct discounts
                        distinct_discounts = {ld.discount for ld in draft.lines if ld.discount}
                        for disc in distinct_discounts:
                            redeem(disc, inv)

                        BillingRunItem.objects.create(
                            run=billing_run,
                            subscription=locked_sub,
                            result=BillingItemResult.CREATED,
                            invoice=inv,
                        )
                        billing_run.created_count += 1

                except IntegrityError:
                    existing_inv = Invoice.objects.filter(
                        subscription=locked_sub,
                        period_start=period_start,
                    ).first()
                    BillingRunItem.objects.create(
                        run=billing_run,
                        subscription=locked_sub,
                        result=BillingItemResult.SKIPPED,
                        invoice=existing_inv,
                        error="Already billed for period",
                    )
                    billing_run.skipped_count += 1

                # Advance pointer and next_invoice_date in both created and skipped cases
                locked_sub.periods_billed += 1
                locked_sub.next_invoice_date = compute_period_start(
                    anchor,
                    locked_sub.periods_billed,
                    plan.interval,
                    plan.interval_count,
                )
                locked_sub.save(update_fields=['periods_billed', 'next_invoice_date', 'updated_at'])

    except Exception as exc:
        # Any unexpected error rolls back this subscription only and records failed item
        sub_instance = Subscription.objects.filter(id=sub_id).first()
        if sub_instance:
            BillingRunItem.objects.create(
                run=billing_run,
                subscription=sub_instance,
                result=BillingItemResult.FAILED,
                error=str(exc),
            )
            billing_run.failed_count += 1


def run_lifecycle(as_of: Optional[date] = None) -> dict:
    """
    Executes automated lifecycle tasks:
      1. Auto-closes expired subscriptions where plan.auto_close=True.
      2. Counts and identifies stale quotations.
      3. Sends automated due-date and overdue payment reminder emails.
    Returns summary dict of actions taken.
    """
    if as_of is None:
        as_of = timezone.localdate()

    from apps.subscriptions.services.lifecycle import auto_close_expired
    from apps.billing.services.reminders import send_due_reminders

    closed_count = auto_close_expired(as_of)

    expired_quotes_count = Subscription.objects.filter(
        status=SubscriptionStatus.QUOTATION,
        quote_valid_until__lt=as_of,
    ).count()

    reminders_sent = send_due_reminders(as_of)

    return {
        "as_of": as_of,
        "auto_closed_subscriptions": closed_count,
        "expired_quotations": expired_quotes_count,
        "reminders_sent": reminders_sent,
    }
