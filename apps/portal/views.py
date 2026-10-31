from decimal import Decimal
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.models import Customer
from apps.billing.models import Invoice, InvoiceStatus
from apps.portal.services.billing import (
    record_payment,
    get_next_invoice_preview,
    pause_subscription,
    resume_subscription,
    renew_subscription,
)
from apps.subscriptions.models import Subscription, SubscriptionStatus


def customer_portal_access(view_func):
    """
    Decorator enforcing Customer Portal access rules:
      - Authenticated users only (unauthenticated -> login)
      - Staff and Admin users are redirected away from the portal to /reports/
      - Ensures a Customer profile exists for the authenticated user.
    """
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")

        user_role = getattr(request.user, "role", None)
        if request.user.is_superuser or user_role in ("admin", "staff") or getattr(request.user, "is_staff", False):
            # Staff users are redirected away from the portal per requirements
            return redirect("/reports/")

        customer = getattr(request.user, "customer_profile", None)
        if not customer:
            customer, _ = Customer.objects.get_or_create(
                user=request.user,
                defaults={"name": request.user.email.split("@")[0]}
            )
        request.customer = customer
        return view_func(request, *args, **kwargs)
    return _wrapped


@customer_portal_access
def portal_dashboard(request):
    """
    Customer portal main dashboard:
      - Customer overview KPI cards
      - Pure next-invoice preview using build_invoice_draft (no DB writes)
      - Quick self-service actions allowed by active plans
      - Recent invoices list
    """
    customer = request.customer

    # Isolated querysets via for_user / customer ownership
    subscriptions = (
        Subscription.objects.filter(customer=customer)
        .select_related("plan")
        .prefetch_related("lines__product", "lines__variant")
        .order_by("-created_at")
    )
    invoices = (
        Invoice.objects.filter(customer=customer)
        .order_by("-invoice_date", "-id")
    )

    active_subs_count = subscriptions.filter(status=SubscriptionStatus.ACTIVE, paused_at__isnull=True).count()
    paused_subs_count = subscriptions.filter(status=SubscriptionStatus.ACTIVE, paused_at__isnull=False).count()

    unpaid_invoices = invoices.filter(status=InvoiceStatus.CONFIRMED, amount_paid__lt=F("total"))
    unpaid_count = unpaid_invoices.count()
    outstanding_balance = sum((inv.total - inv.amount_paid for inv in unpaid_invoices), Decimal("0.00"))

    # Next invoice preview for first eligible active subscription (pure build_invoice_draft, no DB writes)
    active_sub = subscriptions.filter(status=SubscriptionStatus.ACTIVE).first()
    next_preview = get_next_invoice_preview(active_sub) if active_sub else None

    context = {
        "customer": customer,
        "subscriptions": subscriptions[:5],
        "invoices": invoices[:5],
        "active_subs_count": active_subs_count,
        "paused_subs_count": paused_subs_count,
        "unpaid_count": unpaid_count,
        "outstanding_balance": outstanding_balance,
        "next_preview": next_preview,
        "active_sub": active_sub,
        "today": timezone.localdate(),
    }
    return render(request, "portal/dashboard.html", context)


@customer_portal_access
def portal_subscriptions(request):
    """
    Customer's own subscriptions list with plan-controlled self-service actions (pause, renew).
    """
    customer = request.customer
    subscriptions = (
        Subscription.objects.filter(customer=customer)
        .select_related("plan")
        .prefetch_related("lines__product", "lines__variant")
        .order_by("-created_at")
    )

    context = {
        "customer": customer,
        "subscriptions": subscriptions,
        "today": timezone.localdate(),
    }
    return render(request, "portal/subscription_list.html", context)


@customer_portal_access
@require_http_methods(["POST"])
def portal_subscription_pause(request, subscription_id):
    """
    Toggle pause/resume on customer's own subscription (only if allowed by plan).
    Cross-customer access returns 404.
    """
    customer = request.customer
    sub = get_object_or_404(Subscription, pk=subscription_id, customer=customer)

    try:
        if sub.paused_at is not None:
            resume_subscription(sub, user=request.user)
            messages.success(request, f"Subscription #{sub.number} resumed successfully.")
        else:
            pause_subscription(sub, user=request.user)
            messages.info(request, f"Subscription #{sub.number} paused.")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect("/portal/subscriptions/")


@customer_portal_access
@require_http_methods(["POST"])
def portal_subscription_renew(request, subscription_id):
    """
    Self-service renew on customer's own subscription (only if allowed by plan).
    Cross-customer access returns 404.
    """
    customer = request.customer
    sub = get_object_or_404(Subscription, pk=subscription_id, customer=customer)

    try:
        renew_subscription(sub, user=request.user)
        messages.success(request, f"Subscription #{sub.number} renewed until {sub.expiry_date}.")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect("/portal/subscriptions/")


@customer_portal_access
def portal_invoices(request):
    """
    Customer's own invoices list with status, totals, and 'Pay Now' actions.
    """
    customer = request.customer
    invoices = (
        Invoice.objects.filter(customer=customer)
        .select_related("subscription", "subscription__plan")
        .order_by("-invoice_date", "-id")
    )

    context = {
        "customer": customer,
        "invoices": invoices,
        "today": timezone.localdate(),
    }
    return render(request, "portal/invoice_list.html", context)


@customer_portal_access
def portal_invoice_pay(request, identifier):
    """
    Mock payment endpoint for customer's own invoice (/portal/invoices/<id>/pay/).
    Calls billing.services.record_payment with method='card'.
    Cross-customer access returns 404.
    """
    customer = request.customer

    # Isolated lookup: strictly returns 404 if invoice belongs to another customer
    if str(identifier).isdigit():
        invoice = get_object_or_404(
            Invoice,
            Q(pk=int(identifier)) | Q(number=str(identifier)),
            customer=customer
        )
    else:
        invoice = get_object_or_404(Invoice, number=str(identifier), customer=customer)

    balance = max(Decimal("0.00"), invoice.total - invoice.amount_paid)

    if invoice.status == InvoiceStatus.PAID or balance <= Decimal("0.00"):
        messages.info(request, f"Invoice {invoice.number or invoice.id} is already paid in full.")
        return redirect("/portal/invoices/")

    if request.method == "POST":
        try:
            # Calls billing.services record_payment with method=card per requirements
            record_payment(
                invoice=invoice,
                method="card",
                amount=balance,
                paid_on=timezone.localdate(),
                note=f"Payment of {balance} recorded via Card checkout simulation",
                user=request.user,
            )
            messages.success(
                request,
                f"Payment of ₹{balance} recorded successfully for Invoice {invoice.number or invoice.id} via Card."
            )
            return redirect("/portal/invoices/")
        except ValueError as err:
            messages.error(request, f"Payment error: {err}")
            return redirect(f"/portal/invoices/{identifier}/pay/")

    context = {
        "customer": customer,
        "invoice": invoice,
        "balance": balance,
        "today": timezone.localdate(),
    }
    return render(request, "portal/invoice_pay.html", context)
