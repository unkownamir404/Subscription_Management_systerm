from django.shortcuts import render
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import JsonResponse
from apps.reports.services import get_summary


def dashboard_view(request):
    """
    Finance dashboard for Brightloop Software.
    Accessible strictly to Admin and Staff roles. Customers get 403.
    """
    if not request.user.is_authenticated:
        from django.conf import settings
        from django.shortcuts import redirect
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")

    # RBAC verification per DESIGN.md section 7
    user_role = getattr(request.user, "role", None)
    if user_role not in ["admin", "staff"] and not request.user.is_superuser:
        raise PermissionDenied("You do not have permission to view finance reports.")

    # Extract filter parameters from GET
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    subscription_status = request.GET.get("status", "")
    customer_query = request.GET.get("customer", "")

    filters = {
        "date_from": date_from,
        "date_to": date_to,
        "status": subscription_status,
        "customer": customer_query,
    }

    summary = get_summary(filters)

    # Paginate overdue invoices & recent payments tables
    overdue_paginator = Paginator(summary["overdue_invoices"], 5)
    overdue_page_number = request.GET.get("overdue_page", 1)
    overdue_page_obj = overdue_paginator.get_page(overdue_page_number)

    payments_paginator = Paginator(summary["recent_payments"], 5)
    payments_page_number = request.GET.get("payments_page", 1)
    payments_page_obj = payments_paginator.get_page(payments_page_number)

    context = {
        "summary": summary,
        "filters": filters,
        "overdue_page_obj": overdue_page_obj,
        "payments_page_obj": payments_page_obj,
        "ageing_1_30": float(summary["ageing"].get("1-30", 0)),
        "ageing_31_60": float(summary["ageing"].get("31-60", 0)),
        "ageing_60_plus": float(summary["ageing"].get("60+", 0)),
    }

    return render(request, "reports/dashboard.html", context)


def summary_api_view(request):
    """
    API endpoint returning JSON summary for live Chart.js widgets.
    """
    if not request.user.is_authenticated or (
        getattr(request.user, "role", None) not in ["admin", "staff"] and not request.user.is_superuser
    ):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    filters = {
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "status": request.GET.get("status", ""),
        "customer": request.GET.get("customer", ""),
    }
    data = get_summary(filters)

    # Convert Decimal/Date objects to serializable primitives
    serialized_ageing = {k: float(v) for k, v in data["ageing"].items()}

    return JsonResponse({
        "active_subscriptions": data["active_subscriptions"],
        "paused_subscriptions": data["paused_subscriptions"],
        "revenue_collected": float(data["revenue_collected"]),
        "billed": float(data["billed"]),
        "outstanding": float(data["outstanding"]),
        "overdue_count": data["overdue_count"],
        "overdue_amount": float(data["overdue_amount"]),
        "mrr": float(data["mrr"]),
        "arr": float(data["arr"]),
        "ageing": serialized_ageing,
    })

import csv
from django.http import HttpResponse
from django.db.models.functions import TruncMonth, TruncQuarter, TruncYear
from django.db.models import Sum, Count, Q
from apps.billing.models import Invoice, InvoiceStatus, Payment
from apps.subscriptions.models import Subscription, SubscriptionStatus


def financial_reports_view(request):
    """
    Detailed financial tracking: Monthly, Quarterly, and Yearly summaries,
    subscription distribution, and payment collection performance.
    """
    if not request.user.is_authenticated:
        from django.conf import settings
        from django.shortcuts import redirect
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")

    user_role = getattr(request.user, "role", None)
    if user_role not in ["admin", "staff"] and not request.user.is_superuser:
        raise PermissionDenied("You do not have permission to view financial reports.")

    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    period_type = request.GET.get("period", "month")  # month, quarter, year

    invoices = Invoice.objects.exclude(status=InvoiceStatus.CANCELLED)
    if date_from:
        invoices = invoices.filter(invoice_date__gte=date_from)
    if date_to:
        invoices = invoices.filter(invoice_date__lte=date_to)

    if period_type == "quarter":
        trunc_fn = TruncQuarter("invoice_date")
    elif period_type == "year":
        trunc_fn = TruncYear("invoice_date")
    else:
        trunc_fn = TruncMonth("invoice_date")

    breakdown = (
        invoices.annotate(period=trunc_fn)
        .values("period")
        .annotate(
            total_invoices=Count("id"),
            total_billed=Sum("total"),
            total_collected=Sum("amount_paid"),
            total_discount=Sum("discount_total"),
            total_tax=Sum("tax_total"),
        )
        .order_by("-period")[:24]
    )

    # Subscriptions status breakdown
    subs_breakdown = (
        Subscription.objects.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )

    # Global KPI sums
    totals = invoices.aggregate(
        billed=Sum("total"),
        collected=Sum("amount_paid"),
        tax=Sum("tax_total"),
        discounts=Sum("discount_total"),
        count=Count("id"),
    )
    totals["outstanding"] = (totals["billed"] or 0) - (totals["collected"] or 0)

    context = {
        "breakdown": breakdown,
        "subs_breakdown": subs_breakdown,
        "totals": totals,
        "period_type": period_type,
        "date_from": date_from,
        "date_to": date_to,
    }
    return render(request, "reports/financial_summary.html", context)


def export_report_csv_view(request):
    """
    CSV export endpoint for Invoices, Subscriptions, Payments, or Revenue.
    """
    if not request.user.is_authenticated:
        return HttpResponse("Unauthorized", status=401)

    user_role = getattr(request.user, "role", None)
    if user_role not in ["admin", "staff"] and not request.user.is_superuser:
        raise PermissionDenied("Unauthorized")

    report_type = request.GET.get("type", "invoices")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="brightloop_{report_type}_report.csv"'
    writer = csv.writer(response)

    if report_type == "invoices":
        writer.writerow(["Invoice Number", "Customer", "Date", "Due Date", "Status", "Subtotal", "Discount", "Tax", "Total", "Paid", "Balance"])
        for inv in Invoice.objects.select_related("customer").order_by("-invoice_date")[:1000]:
            writer.writerow([
                inv.number or f"DRAFT-{inv.id}",
                inv.customer.name,
                inv.invoice_date,
                inv.due_date,
                inv.status,
                inv.subtotal,
                inv.discount_total,
                inv.tax_total,
                inv.total,
                inv.amount_paid,
                inv.total - inv.amount_paid,
            ])
    elif report_type == "subscriptions":
        writer.writerow(["Subscription Number", "Customer", "Plan", "Status", "Start Date", "Expiry Date", "Next Invoice Date"])
        for s in Subscription.objects.select_related("customer", "plan").order_by("-created_at")[:1000]:
            writer.writerow([
                s.number,
                s.customer.name,
                s.plan.name,
                s.status,
                s.start_date,
                s.expiry_date or "Indefinite",
                s.next_invoice_date or "—",
            ])
    elif report_type == "payments":
        writer.writerow(["Payment ID", "Date", "Invoice", "Customer", "Method", "Amount", "Note"])
        for p in Payment.objects.select_related("invoice__customer").order_by("-paid_on")[:1000]:
            writer.writerow([
                p.id,
                p.paid_on,
                p.invoice.number or p.invoice.id,
                p.invoice.customer.name,
                p.get_method_display(),
                p.amount,
                p.note or "",
            ])
    else:
        # Default revenue breakdown
        writer.writerow(["Month", "Invoices Count", "Billed", "Collected", "Tax", "Discounts"])
        months = (
            Invoice.objects.exclude(status=InvoiceStatus.CANCELLED)
            .annotate(month=TruncMonth("invoice_date"))
            .values("month")
            .annotate(
                cnt=Count("id"),
                billed=Sum("total"),
                collected=Sum("amount_paid"),
                tax=Sum("tax_total"),
                disc=Sum("discount_total"),
            )
            .order_by("-month")[:36]
        )
        for m in months:
            writer.writerow([
                m["month"].strftime("%Y-%m") if m["month"] else "—",
                m["cnt"],
                m["billed"] or 0,
                m["collected"] or 0,
                m["tax"] or 0,
                m["disc"] or 0,
            ])

    return response
