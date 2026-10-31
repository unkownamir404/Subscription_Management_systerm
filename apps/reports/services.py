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
