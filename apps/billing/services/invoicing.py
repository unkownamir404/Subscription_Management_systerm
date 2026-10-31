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


# Re-export state machine actions
from apps.billing.services.invoice_actions import (
    confirm_invoice,
    cancel_invoice,
    mark_sent,
    record_payment,
)

