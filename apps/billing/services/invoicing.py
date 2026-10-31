from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional, Tuple
from dateutil.relativedelta import relativedelta
from apps.billing.services.discounts import find_best_discounts
from apps.billing.services.tax import compute_tax, round_money


@dataclass(frozen=True)
class InvoiceLineDraft:
    description: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    discount: Optional[Any]
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal
    product: Optional[Any] = None


@dataclass(frozen=True)
class InvoiceDraft:
    subscription: Any
    customer: Any
    period_start: date
    period_end: date
    invoice_date: date
    due_date: date
    lines: Tuple[InvoiceLineDraft, ...]
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal


def compute_period_end(period_start: date, interval: str, interval_count: int = 1) -> date:
    """
    Compute period_end = period_start(n+1) - 1 day using relativedelta.
    """
    count = max(1, interval_count)
    if interval == 'daily':
        delta = relativedelta(days=count)
    elif interval == 'weekly':
        delta = relativedelta(weeks=count)
    elif interval == 'monthly':
        delta = relativedelta(months=count)
    elif interval == 'yearly':
        delta = relativedelta(years=count)
    else:
        delta = relativedelta(months=count)

    next_period_start = period_start + delta
    return next_period_start - timedelta(days=1)


def build_invoice_draft(subscription: Any, period_start: date) -> InvoiceDraft:
    """
    Build a pure, immutable draft invoice representation.
    Must NOT write to the database.
    """
    plan = subscription.plan
    interval = getattr(plan, 'interval', 'monthly')
    interval_count = getattr(plan, 'interval_count', 1)

    period_end = compute_period_end(period_start, interval, interval_count)
    invoice_date = period_start
    payment_terms_days = getattr(subscription, 'payment_terms_days', 15) or 15
    due_date = invoice_date + timedelta(days=payment_terms_days)

    if hasattr(subscription.lines, 'all'):
        sub_lines = list(subscription.lines.select_related('product', 'variant'))
    else:
        sub_lines = list(subscription.lines)

    discount_results = find_best_discounts(sub_lines, on_date=period_start)

    draft_lines = []
    subtotal = Decimal('0.00')
    discount_total = Decimal('0.00')
    tax_total = Decimal('0.00')

    for i, line in enumerate(sub_lines):
        product = getattr(line, 'product', None)
        variant = getattr(line, 'variant', None)

        prod_name = getattr(product, 'name', 'Item')
        if variant and getattr(variant, 'value', None):
            description = f"{prod_name} ({variant.value})"
        else:
            description = prod_name

        qty = int(getattr(line, 'quantity', 1))
        unit_price = round_money(getattr(line, 'unit_price', Decimal('0.00')))
        line_sub = round_money(unit_price * qty)

        alloc = discount_results.line_allocations[i] if i < len(discount_results.line_allocations) else None
        disc_amt = alloc.total_discount_amount if alloc else Decimal('0.00')
        disc_ref = None
        if alloc:
            disc_ref = alloc.product_discount or alloc.subscription_discount or discount_results.subscription_discount

        net = line_sub - disc_amt
        tax_rate = Decimal(str(getattr(line, 'tax_rate', '0.00')))
        tax_amt = compute_tax(net, tax_rate)
        line_tot = net + tax_amt

        subtotal += line_sub
        discount_total += disc_amt
        tax_total += tax_amt

        draft_lines.append(
            InvoiceLineDraft(
                description=description,
                quantity=qty,
                unit_price=unit_price,
                discount_amount=disc_amt,
                discount=disc_ref,
                tax_rate=tax_rate,
                tax_amount=tax_amt,
                line_total=line_tot,
                product=product,
            )
        )

    # Reconciled total = subtotal - discount_total + tax_total
    total = subtotal - discount_total + tax_total

    return InvoiceDraft(
        subscription=subscription,
        customer=subscription.customer,
        period_start=period_start,
        period_end=period_end,
        invoice_date=invoice_date,
        due_date=due_date,
        lines=tuple(draft_lines),
        subtotal=subtotal,
        discount_total=discount_total,
        tax_total=tax_total,
        total=total,
    )
import logging
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from apps.core.exceptions import DomainError
from apps.billing.models import Invoice, InvoiceCounter, InvoiceLine, InvoiceStatus
from apps.billing.services.discounts import redeem

logger = logging.getLogger(__name__)


def create_invoice_from_draft(subscription, draft: InvoiceDraft) -> Invoice:
    """
    Creates an Invoice (status=draft) and InvoiceLine rows from an InvoiceDraft.
    Redeems distinct discounts atomically. If a discount fails redemption (e.g. usage limit reached),
    recomputes the draft without that discount.
    """
    with transaction.atomic():
        # Check discount redemptions
        active_draft = draft
        distinct_discounts = [ld.discount for ld in active_draft.lines if ld.discount]
        needs_recompute = False

        for disc in distinct_discounts:
            # Test redemption eligibility
            if disc.usage_limit is not None and disc.used_count >= disc.usage_limit:
                needs_recompute = True
                break

        if needs_recompute:
            # Recompute draft with currently valid discounts
            active_draft = build_invoice_draft(subscription, draft.period_start)

        invoice = Invoice.objects.create(
            subscription=subscription,
            customer=active_draft.customer,
            period_start=active_draft.period_start,
            period_end=active_draft.period_end,
            invoice_date=active_draft.invoice_date,
            due_date=active_draft.due_date,
            status=InvoiceStatus.DRAFT,
            subtotal=active_draft.subtotal,
            discount_total=active_draft.discount_total,
            tax_total=active_draft.tax_total,
            total=active_draft.total,
            amount_paid=Decimal("0.00"),
        )

        for ld in active_draft.lines:
            InvoiceLine.objects.create(
                invoice=invoice,
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

        # Redeem discounts atomically
        redeemed_discounts = {ld.discount for ld in active_draft.lines if ld.discount}
        for disc in redeemed_discounts:
            redeem(disc, invoice)

    return invoice

def generate_invoice_for_subscription(subscription: Any, period_start: Optional[date] = None) -> Invoice:
    """
    Generate an invoice directly from an active subscription.
    Checks status, prevents duplicate billing, advances pointer, and returns created Invoice.
    """
    if getattr(subscription, 'status', None) != 'active':
        raise DomainError(f"Cannot generate invoice for subscription with status '{subscription.status}'. Subscription must be active.")
    if subscription.paused_at is not None:
        raise DomainError("Cannot generate invoice for a paused subscription. Resume subscription first.")

    target_start = period_start or subscription.next_invoice_date or subscription.billing_anchor or subscription.start_date
    if Invoice.objects.filter(subscription=subscription, period_start=target_start).exists():
        raise DomainError(f"An invoice for subscription {subscription.number} starting on {target_start} already exists.")

    from apps.billing.services.billing_run import compute_period_start
    draft = build_invoice_draft(subscription, target_start)
    inv = create_invoice_from_draft(subscription, draft)

    # Advance subscription period
    plan = subscription.plan
    anchor = subscription.billing_anchor or subscription.start_date
    subscription.periods_billed += 1
    subscription.next_invoice_date = compute_period_start(
        anchor,
        subscription.periods_billed,
        plan.interval,
        plan.interval_count,
    )
    subscription.save(update_fields=['periods_billed', 'next_invoice_date', 'updated_at'])

    return inv


def cancel_invoice(invoice: Invoice, user=None) -> Invoice:
    """
    Cancels an invoice (only if draft or confirmed, and amount_paid == 0).
    Cancelled invoices retain their billing period.
    """
    if invoice.status not in (InvoiceStatus.DRAFT, InvoiceStatus.CONFIRMED):
        raise DomainError(f"Cannot cancel invoice in '{invoice.status}' status.")

    if invoice.amount_paid > Decimal("0.00"):
        raise DomainError("Cannot cancel an invoice with payments recorded. Refund or adjust payments first.")

    with transaction.atomic():
        inv = Invoice.objects.select_for_update(of=("self",)).get(pk=invoice.pk)
        inv.status = InvoiceStatus.CANCELLED
        inv.save(update_fields=["status", "updated_at"])

    return inv


def send_invoice(invoice: Invoice, user=None) -> Invoice:
    """
    Sends invoice by email (only if confirmed or paid).
    Renders plain text email to customer's user email.
    Sends on commit and records sent_at timestamp.
    """
    if invoice.status not in (InvoiceStatus.CONFIRMED, InvoiceStatus.PAID):
        raise DomainError(f"Cannot send invoice in '{invoice.status}' status. Must be confirmed or paid.")

    recipient_email = getattr(getattr(invoice.customer, "user", None), "email", None)
    if not recipient_email:
        logger.warning(f"Customer #{invoice.customer.id} has no user email; skipping email dispatch.")
        invoice.sent_at = timezone.now()
        invoice.save(update_fields=["sent_at", "updated_at"])
        return invoice

    subject = f"Invoice {invoice.number or invoice.id} from Brightloop"
    message = (
        f"Dear {invoice.customer.name},\n\n"
        f"Your invoice {invoice.number or invoice.id} for the period "
        f"{invoice.period_start} to {invoice.period_end} is ready.\n\n"
        f"Total Amount: ₹ {invoice.total}\n"
        f"Amount Paid: ₹ {invoice.amount_paid}\n"
        f"Balance Due: ₹ {invoice.total - invoice.amount_paid}\n"
        f"Due Date: {invoice.due_date}\n\n"
        f"View and pay your invoice at http://127.0.0.1:8000/portal/invoices/\n\n"
        f"Thank you for choosing Brightloop!"
    )

    def _deliver():
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=None,
                recipient_list=[recipient_email],
                fail_silently=True,
            )
        except Exception as exc:
            logger.error(f"Failed to deliver invoice email to {recipient_email}: {exc}")

    transaction.on_commit(_deliver)
    invoice.sent_at = timezone.now()
    invoice.save(update_fields=["sent_at", "updated_at"])
    return invoice


def confirm_invoice(invoice: Invoice, user=None) -> Invoice:
    """
    Transitions invoice from draft -> confirmed.
    Assigns sequential, gap-free invoice number INV-<year>-<6 digits> under a row lock on InvoiceCounter.
    Automatically schedules invoice notification email dispatch on transaction commit.
    """
    if invoice.status != InvoiceStatus.DRAFT:
        raise DomainError(f"Cannot confirm invoice with status '{invoice.status}'. Must be 'draft'.")

    with transaction.atomic():
        inv = Invoice.objects.select_for_update(of=("self",)).get(pk=invoice.pk)
        year = inv.invoice_date.year
        key = f"INV-{year}"

        counter, _ = InvoiceCounter.objects.select_for_update().get_or_create(
            key=key,
            defaults={"last_value": 0},
        )
        counter.last_value += 1
        counter.save(update_fields=["last_value", "updated_at"])

        inv.number = f"{key}-{counter.last_value:06d}"
        inv.status = InvoiceStatus.CONFIRMED
        inv.save(update_fields=["number", "status", "updated_at"])

    # Auto-dispatch notification email to customer
    try:
        send_invoice(inv, user)
    except Exception:
        pass

    return inv
