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
