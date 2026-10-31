from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView, ListView, DetailView

from apps.billing.models import Invoice
from apps.billing.services.invoicing import build_invoice_draft
from apps.billing.services.payments import record_payment
from apps.subscriptions.models import Subscription
from apps.subscriptions.services import transitions


class CustomerPortalMixin:
    """
    Ensures that:
    1. Unauthenticated users are redirected to login.
    2. Staff and Admin users are redirected away from the portal (e.g. to /subscriptions/).
    3. Customers are granted access.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())

        user_role = getattr(request.user, "role", None)
        if request.user.is_superuser or user_role in ("admin", "staff") or request.user.is_staff:
            return redirect("/subscriptions/")

        return super().dispatch(request, *args, **kwargs)


class PortalDashboardView(CustomerPortalMixin, TemplateView):
    template_name = "portal/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        customer = getattr(user, "customer_profile", None)

        subs = Subscription.objects.for_user(user).select_related("plan")
        invoices = Invoice.objects.for_user(user).select_related("subscription")

        active_subs = subs.filter(status="active", paused_at__isnull=True)
        unpaid_invoices = invoices.filter(status="confirmed")

        outstanding = sum((inv.balance_due for inv in unpaid_invoices), Decimal("0.00"))
        today = timezone.now().date()
        overdue_count = unpaid_invoices.filter(due_date__lt=today).count()

        # Primary subscription for next-invoice preview
        primary_sub = active_subs.first() or subs.first()
        next_invoice_preview = None
        if primary_sub and primary_sub.next_invoice_date:
            try:
                next_invoice_preview = build_invoice_draft(primary_sub, primary_sub.next_invoice_date)
            except Exception:
                next_invoice_preview = None

        ctx["customer"] = customer
        ctx["active_subs_count"] = active_subs.count()
        ctx["outstanding_balance"] = outstanding
        ctx["overdue_count"] = overdue_count
        ctx["primary_sub"] = primary_sub
        ctx["next_invoice_preview"] = next_invoice_preview
        ctx["recent_invoices"] = invoices[:5]
        ctx["subscriptions"] = subs[:5]
        return ctx


class PortalSubscriptionListView(CustomerPortalMixin, ListView):
    model = Subscription
    template_name = "portal/subscription_list.html"
    context_object_name = "subscriptions"
    paginate_by = 25

    def get_queryset(self):
        return Subscription.objects.for_user(self.request.user).select_related("plan")


class PortalSubscriptionDetailView(CustomerPortalMixin, DetailView):
    model = Subscription
    template_name = "portal/subscription_detail.html"
    context_object_name = "subscription"

    def get_queryset(self):
        # Strict for_user isolation; another customer's ID returns 404
        return (
            Subscription.objects.for_user(self.request.user)
            .select_related("customer", "plan")
            .prefetch_related("lines__product", "lines__variant", "events")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sub = self.object

        # Next-invoice preview without writing to database
        preview = None
        if sub.status == "active" and sub.next_invoice_date and not sub.paused_at:
            try:
                preview = build_invoice_draft(sub, sub.next_invoice_date)
            except Exception:
                preview = None

        ctx["preview"] = preview
        ctx["lines"] = sub.lines.all()
        ctx["events"] = sub.events.all()
        return ctx


class PortalSubscriptionActionView(CustomerPortalMixin, View):
    """
    Self-service actions allowed by the plan (pause, resume, renew).
    """
    def post(self, request, pk, action):
        sub = get_object_or_404(Subscription.objects.for_user(request.user), pk=pk)

        try:
            if action == "pause":
                if not sub.plan.allow_pause:
                    raise ValidationError("Your plan does not allow pausing.")
                transitions.pause_subscription(sub, user=request.user, note="Customer self-service pause.")
                messages.success(request, "Your subscription has been paused.")
            elif action == "resume":
                transitions.resume_subscription(sub, user=request.user, note="Customer self-service resume.")
                messages.success(request, "Your subscription has been resumed.")
            elif action == "renew":
                if not sub.plan.allow_renew:
                    raise ValidationError("Your plan does not allow self-service renewal.")
                transitions.renew_subscription(sub, user=request.user, note="Customer self-service renew.")
                messages.success(request, "Your subscription has been renewed for another term.")
            else:
                messages.error(request, "Invalid action requested.")
        except ValidationError as exc:
            for msg in exc.messages if hasattr(exc, "messages") else [str(exc)]:
                messages.error(request, msg)

        return redirect("portal:subscription_detail", pk=pk)


class PortalInvoiceListView(CustomerPortalMixin, ListView):
    model = Invoice
    template_name = "portal/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 25

    def get_queryset(self):
        return Invoice.objects.for_user(self.request.user).select_related("subscription")


class PortalInvoiceDetailView(CustomerPortalMixin, DetailView):
    model = Invoice
    template_name = "portal/invoice_detail.html"
    context_object_name = "invoice"

    def get_queryset(self):
        # Strict for_user isolation; another customer's ID returns 404
        return (
            Invoice.objects.for_user(self.request.user)
            .select_related("subscription", "customer")
            .prefetch_related("lines__product", "payments")
        )


class PortalPayInvoiceView(CustomerPortalMixin, View):
    """
    Mock payment endpoint: calls billing.services.payments.record_payment with method=card.
    Strictly isolated via for_user: accessing another customer's invoice returns 404.
    """
    def get(self, request, pk):
        invoice = get_object_or_404(Invoice.objects.for_user(request.user), pk=pk)
        return render(request, "portal/pay_invoice.html", {"invoice": invoice})

    def post(self, request, pk):
        invoice = get_object_or_404(Invoice.objects.for_user(request.user), pk=pk)
        balance = invoice.balance_due

        if balance <= Decimal("0.00"):
            messages.info(request, "This invoice is already settled.")
            return redirect("portal:invoice_detail", pk=pk)

        try:
            record_payment(
                invoice=invoice,
                method="card",
                amount=balance,
                note="Mock customer payment via Portal",
                user=request.user,
            )
            messages.success(request, f"Payment of ₹{balance} successful! Invoice #{invoice.number or invoice.id} is now paid.")
            return redirect("portal:invoice_detail", pk=pk)
        except ValidationError as exc:
            for err in exc.messages if hasattr(exc, "messages") else [str(exc)]:
                messages.error(request, err)
            return redirect("portal:pay_invoice", pk=pk)
