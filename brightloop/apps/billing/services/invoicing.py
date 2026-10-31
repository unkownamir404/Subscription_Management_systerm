from dataclasses import dataclass, field
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from typing import List, Optional

from apps.billing.services.tax import compute_tax, round_money
from apps.catalog.models import Discount, Product


@dataclass(frozen=True)
class InvoiceLineDraft:
    description: str
    product_id: Optional[int]
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal
    discount_id: Optional[int] = None


@dataclass(frozen=True)
class InvoiceDraft:
    subscription_id: int
    customer_id: int
    period_start: date
    period_end: date
    invoice_date: date
    due_date: date
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    lines: List[InvoiceLineDraft] = field(default_factory=list)


def compute_period_end(period_start: date, interval: str, count: int) -> date:
    interval_map = {
        "daily": relativedelta(days=count),
        "weekly": relativedelta(weeks=count),
        "monthly": relativedelta(months=count),
        "yearly": relativedelta(years=count),
    }
    next_start = period_start + interval_map.get(interval, relativedelta(months=count))
    return next_start - timedelta(days=1)


def build_invoice_draft(subscription, period_start: date) -> InvoiceDraft:
    """
    Pure function building an in-memory draft of the next invoice.
    Does not write to the database.
    """
    plan = subscription.plan
    period_end = compute_period_end(period_start, plan.interval, plan.interval_count)
    invoice_date = period_start
    due_date = invoice_date + timedelta(days=subscription.payment_terms_days)

    lines: List[InvoiceLineDraft] = []
    subtotal = Decimal("0.00")
    discount_total = Decimal("0.00")
    tax_total = Decimal("0.00")

    sub_lines = subscription.lines.all()
    for s_line in sub_lines:
        line_sub = round_money(s_line.unit_price * s_line.quantity)
        disc_amt = Decimal("0.00")
        line_net = line_sub - disc_amt
        line_tax = compute_tax(line_net, s_line.tax_rate)
        line_tot = line_net + line_tax

        subtotal += line_sub
        discount_total += disc_amt
        tax_total += line_tax

        desc = f"{s_line.product.name}"
        if s_line.variant:
            desc += f" ({s_line.variant.attribute}: {s_line.variant.value})"

        lines.append(
            InvoiceLineDraft(
                description=desc,
                product_id=s_line.product_id,
                quantity=s_line.quantity,
                unit_price=s_line.unit_price,
                discount_amount=disc_amt,
                tax_rate=s_line.tax_rate,
                tax_amount=line_tax,
                line_total=line_tot,
            )
        )

    total = subtotal - discount_total + tax_total

    return InvoiceDraft(
        subscription_id=subscription.id,
        customer_id=subscription.customer_id,
        period_start=period_start,
        period_end=period_end,
        invoice_date=invoice_date,
        due_date=due_date,
        subtotal=subtotal,
        discount_total=discount_total,
        tax_total=tax_total,
        total=total,
        lines=lines,
    )
