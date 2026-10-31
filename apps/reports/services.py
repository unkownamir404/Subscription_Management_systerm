"""
Real database aggregation service for Brightloop Subscription Management System.
Computes summary finance KPIs, MRR/ARR, aging buckets, overdue invoices, and recent payments
using single-pass SQL aggregations (no Python row looping) to maintain sub-2-second SLAs.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from django.apps import apps
from django.db.models import Sum, Count, Q, F, DecimalField
from django.utils import timezone


def get_summary(filters=None):
    """
    Computes real-time subscription & billing summary metrics from the database.
    Shape matches the C1 stub contract:
    {
        "active_subscriptions": int,
        "paused_subscriptions": int,
        "revenue_collected": Decimal,
        "billed": Decimal,
        "outstanding": Decimal,
        "overdue_count": int,
        "overdue_amount": Decimal,
        "mrr": Decimal,
        "arr": Decimal,
        "ageing": {"1-30": Decimal, "31-60": Decimal, "60+": Decimal},
        "recent_payments": list[dict],
        "overdue_invoices": list[dict]
    }
    """
    filters = filters or {}
    today = timezone.localdate()

    try:
        Subscription = apps.get_model("subscriptions", "Subscription")
        SubscriptionLine = apps.get_model("subscriptions", "SubscriptionLine")
        Invoice = apps.get_model("billing", "Invoice")
        Payment = apps.get_model("billing", "Payment")
    except LookupError:
        # Fallback when domain apps are not registered in isolated environment
        return {
            "active_subscriptions": 0,
            "paused_subscriptions": 0,
            "revenue_collected": Decimal("0.00"),
            "billed": Decimal("0.00"),
            "outstanding": Decimal("0.00"),
            "overdue_count": 0,
            "overdue_amount": Decimal("0.00"),
            "mrr": Decimal("0.00"),
            "arr": Decimal("0.00"),
            "ageing": {
                "1-30": Decimal("0.00"),
                "31-60": Decimal("0.00"),
                "60+": Decimal("0.00"),
            },
            "recent_payments": [],
            "overdue_invoices": [],
        }

    # Build filter conditions
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    status_filter = filters.get("status")
    customer_query = filters.get("customer")

    sub_q = Q()
    inv_q = Q()
    pay_q = Q()

    if status_filter:
        sub_q &= Q(status=status_filter)
        inv_q &= Q(subscription__status=status_filter)

    if customer_query:
        cust_match = (
            Q(customer__name__icontains=customer_query)
            | Q(customer__company__icontains=customer_query)
        )
        sub_q &= cust_match
        inv_q &= cust_match
        pay_q &= (
            Q(invoice__customer__name__icontains=customer_query)
            | Q(invoice__customer__company__icontains=customer_query)
        )

    # Date range filters
    pay_date_q = Q()
    inv_date_q = Q()
    if date_from:
        pay_date_q &= Q(paid_on__gte=date_from)
        inv_date_q &= Q(invoice_date__gte=date_from)
    if date_to:
        pay_date_q &= Q(paid_on__lte=date_to)
        inv_date_q &= Q(invoice_date__lte=date_to)

    # 1. Subscriptions Aggregation (Active vs Paused)
    sub_agg = Subscription.objects.filter(sub_q).aggregate(
        active=Count("id", filter=Q(status="active", paused_at__isnull=True)),
        paused=Count("id", filter=Q(status="active", paused_at__isnull=False)),
    )
    active_count = sub_agg["active"] or 0
    paused_count = sub_agg["paused"] or 0

    # 2. Revenue Collected (Payment.amount within date range)
    rev_agg = Payment.objects.filter(pay_q & pay_date_q).aggregate(
        collected=Sum("amount", output_field=DecimalField(max_digits=14, decimal_places=2))
    )
    revenue_collected = (rev_agg["collected"] or Decimal("0.00")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # 3. Invoices Aggregation: Billed, Outstanding, Overdue & Aging Buckets
    # Overdue boundary: due_date < today and status='confirmed'
    date_1_30 = today - timedelta(days=30)
    date_31_60 = today - timedelta(days=60)

    q_overdue = Q(status="confirmed", due_date__lt=today)
    q_1_30 = q_overdue & Q(due_date__gte=date_1_30)
    q_31_60 = q_overdue & Q(due_date__lt=date_1_30, due_date__gte=date_31_60)
    q_60_plus = q_overdue & Q(due_date__lt=date_31_60)

    inv_agg = Invoice.objects.filter(inv_q).aggregate(
        billed=Sum(
            "total",
            filter=Q(status__in=["confirmed", "paid"]) & inv_date_q,
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        outstanding=Sum(
            F("total") - F("amount_paid"),
            filter=Q(status="confirmed"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        overdue_count=Count("id", filter=q_overdue),
        overdue_amount=Sum(
            F("total") - F("amount_paid"),
            filter=q_overdue,
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        b_1_30=Sum(
            F("total") - F("amount_paid"),
            filter=q_1_30,
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        b_31_60=Sum(
            F("total") - F("amount_paid"),
            filter=q_31_60,
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        b_60_plus=Sum(
            F("total") - F("amount_paid"),
            filter=q_60_plus,
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
    )

    billed = (inv_agg["billed"] or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    outstanding = (inv_agg["outstanding"] or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    overdue_count = inv_agg["overdue_count"] or 0
    overdue_amount = (inv_agg["overdue_amount"] or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ageing_1_30 = (inv_agg["b_1_30"] or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ageing_31_60 = (inv_agg["b_31_60"] or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ageing_60_plus = (inv_agg["b_60_plus"] or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 4. MRR & ARR Normalization from active, non-paused subscription lines
    # Formula: daily * 30, weekly * 52/12, monthly * 1, yearly / 12, divided by interval_count
    line_q = Q(subscription__status="active", subscription__paused_at__isnull=True)
    if customer_query:
        line_q &= (
            Q(subscription__customer__name__icontains=customer_query)
            | Q(subscription__customer__company__icontains=customer_query)
        )

    mrr_agg = SubscriptionLine.objects.filter(line_q).aggregate(
        daily=Sum(
            (F("unit_price") * F("quantity")) / F("subscription__plan__interval_count"),
            filter=Q(subscription__plan__interval="daily"),
            output_field=DecimalField(max_digits=14, decimal_places=4),
        ),
        weekly=Sum(
            (F("unit_price") * F("quantity")) / F("subscription__plan__interval_count"),
            filter=Q(subscription__plan__interval="weekly"),
            output_field=DecimalField(max_digits=14, decimal_places=4),
        ),
        monthly=Sum(
            (F("unit_price") * F("quantity")) / F("subscription__plan__interval_count"),
            filter=Q(subscription__plan__interval="monthly"),
            output_field=DecimalField(max_digits=14, decimal_places=4),
        ),
        yearly=Sum(
            (F("unit_price") * F("quantity")) / F("subscription__plan__interval_count"),
            filter=Q(subscription__plan__interval="yearly"),
            output_field=DecimalField(max_digits=14, decimal_places=4),
        ),
    )

    d_val = mrr_agg["daily"] or Decimal("0.00")
    w_val = mrr_agg["weekly"] or Decimal("0.00")
    m_val = mrr_agg["monthly"] or Decimal("0.00")
    y_val = mrr_agg["yearly"] or Decimal("0.00")

    # MRR = (daily * 30) + (weekly * 52/12) + (monthly * 1) + (yearly / 12)
    mrr_raw = (
        (d_val * Decimal("30.00"))
        + (w_val * Decimal("52.00") / Decimal("12.00"))
        + (m_val * Decimal("1.00"))
        + (y_val / Decimal("12.00"))
    )
    mrr = mrr_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    arr = (mrr * Decimal("12.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 5. Overdue Invoices (List)
    overdue_qs = (
        Invoice.objects.filter(q_overdue & inv_q)
        .select_related("customer")
        .order_by("due_date", "-id")[:50]
    )
    overdue_invoices = [
        {
            "number": inv.number or f"DRAFT-{inv.id}",
            "customer": inv.customer.name,
            "due_date": inv.due_date,
            "balance": (inv.total - inv.amount_paid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "days_overdue": (today - inv.due_date).days,
        }
        for inv in overdue_qs
    ]

    # 6. Recent Payments (List)
    pay_qs = (
        Payment.objects.filter(pay_q & pay_date_q)
        .select_related("invoice", "invoice__customer")
        .order_by("-paid_on", "-id")[:50]
    )
    recent_payments = [
        {
            "invoice_number": p.invoice.number or f"DRAFT-{p.invoice.id}",
            "customer": p.invoice.customer.name,
            "amount": p.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "method": p.method,
            "paid_on": p.paid_on,
        }
        for p in pay_qs
    ]

    return {
        "active_subscriptions": active_count,
        "paused_subscriptions": paused_count,
        "revenue_collected": revenue_collected,
        "billed": billed,
        "outstanding": outstanding,
        "overdue_count": overdue_count,
        "overdue_amount": overdue_amount,
        "mrr": mrr,
        "arr": arr,
        "ageing": {
            "1-30": ageing_1_30,
            "31-60": ageing_31_60,
            "60+": ageing_60_plus,
        },
        "recent_payments": recent_payments,
        "overdue_invoices": overdue_invoices,
    }



def get_invoice_calculation_breakdown(invoice):
    """
    Computes a transparent, frozen-data calculation breakdown for an invoice
    to power the 'Why this amount?' panel per DESIGN.md sections 5.1, 5.3, 5.4.
    
    Uses strictly frozen InvoiceLine data:
      - Unit price with variant extra snapshotted at creation
      - Line quantity
      - Line discount amount and its source (rule / template / promotion)
      - Tax rate and tax amount computed on the discounted net
      - Verified reconciliation against invoice subtotal, discount_total, tax_total, and total.
    """
    lines_breakdown = []
    calc_subtotal = Decimal("0.00")
    calc_discount_total = Decimal("0.00")
    calc_tax_total = Decimal("0.00")
    calc_total = Decimal("0.00")
    tax_groups = {}

    lines = invoice.lines.all().select_related("product", "discount") if hasattr(invoice, "lines") else []

    for line in lines:
        qty = int(getattr(line, "quantity", 1))
        unit_price = getattr(line, "unit_price", Decimal("0.00"))
        if not isinstance(unit_price, Decimal):
            unit_price = Decimal(str(unit_price))

        gross = (Decimal(qty) * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        disc_amt = getattr(line, "discount_amount", Decimal("0.00")) or Decimal("0.00")
        if not isinstance(disc_amt, Decimal):
            disc_amt = Decimal(str(disc_amt))

        discount_source = "None"
        if getattr(line, "discount", None):
            kind_str = line.discount.get_kind_display() if hasattr(line.discount, "get_kind_display") else getattr(line.discount, "kind", "Discount")
            discount_source = f"{line.discount.name} ({kind_str})"
        elif disc_amt > Decimal("0.00"):
            discount_source = "Subscription / Plan Discount"

        discounted_net = gross - disc_amt
        tax_rate = getattr(line, "tax_rate", Decimal("0.00")) or Decimal("0.00")
        if not isinstance(tax_rate, Decimal):
            tax_rate = Decimal(str(tax_rate))

        tax_amount = getattr(line, "tax_amount", Decimal("0.00")) or Decimal("0.00")
        if not isinstance(tax_amount, Decimal):
            tax_amount = Decimal(str(tax_amount))

        line_total = getattr(line, "line_total", Decimal("0.00")) or Decimal("0.00")
        if not isinstance(line_total, Decimal):
            line_total = Decimal(str(line_total))

        calc_subtotal += gross
        calc_discount_total += disc_amt
        calc_tax_total += tax_amount
        calc_total += line_total

        rate_key = f"{tax_rate:.2f}%"
        if rate_key not in tax_groups:
            tax_groups[rate_key] = {
                "rate": tax_rate,
                "taxable_amount": Decimal("0.00"),
                "tax_amount": Decimal("0.00"),
            }
        tax_groups[rate_key]["taxable_amount"] += discounted_net
        tax_groups[rate_key]["tax_amount"] += tax_amount

        lines_breakdown.append({
            "line": line,
            "description": getattr(line, "description", "Item"),
            "quantity": qty,
            "unit_price": unit_price,
            "gross": gross,
            "discount_amount": disc_amt,
            "discount_source": discount_source,
            "discounted_net": discounted_net,
            "tax_rate": tax_rate,
            "tax_amount": tax_amount,
            "line_total": line_total,
        })

    amount_paid = getattr(invoice, "amount_paid", Decimal("0.00")) or Decimal("0.00")
    if not isinstance(amount_paid, Decimal):
        amount_paid = Decimal(str(amount_paid))

    inv_total = getattr(invoice, "total", Decimal("0.00")) or Decimal("0.00")
    if not isinstance(inv_total, Decimal):
        inv_total = Decimal(str(inv_total))

    inv_subtotal = getattr(invoice, "subtotal", Decimal("0.00")) or Decimal("0.00")
    if not isinstance(inv_subtotal, Decimal):
        inv_subtotal = Decimal(str(inv_subtotal))

    inv_discount_total = getattr(invoice, "discount_total", Decimal("0.00")) or Decimal("0.00")
    if not isinstance(inv_discount_total, Decimal):
        inv_discount_total = Decimal(str(inv_discount_total))

    inv_tax_total = getattr(invoice, "tax_total", Decimal("0.00")) or Decimal("0.00")
    if not isinstance(inv_tax_total, Decimal):
        inv_tax_total = Decimal(str(inv_tax_total))

    balance = max(Decimal("0.00"), inv_total - amount_paid)

    reconciled = (
        calc_subtotal == inv_subtotal and
        calc_discount_total == inv_discount_total and
        calc_tax_total == inv_tax_total and
        calc_total == inv_total
    )

    return {
        "lines": lines_breakdown,
        "tax_groups": list(tax_groups.values()),
        "calc_subtotal": calc_subtotal,
        "calc_discount_total": calc_discount_total,
        "calc_tax_total": calc_tax_total,
        "calc_total": calc_total,
        "invoice_subtotal": inv_subtotal,
        "invoice_discount_total": inv_discount_total,
        "invoice_tax_total": inv_tax_total,
        "invoice_total": inv_total,
        "amount_paid": amount_paid,
        "balance": balance,
        "reconciled": reconciled,
    }
