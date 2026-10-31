from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.db.models import Q, F, Count
from django.http import Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import RoleRequiredMixin
from apps.billing.models import Invoice, InvoiceStatus
from apps.reports.services import get_invoice_calculation_breakdown
from apps.subscriptions.models import Subscription, SubscriptionStatus


class InvoiceListView(RoleRequiredMixin, ListView):
    """
    Paginated invoice list view for Brightloop staff and administrators.
    Allows filtering by status, date range, and customer name / invoice number.
    Raises 403 PermissionDenied for customers.
    """
    model = Invoice
    template_name = "billing/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 25
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        qs = (
            Invoice.objects.select_related("customer", "subscription__plan")
            .order_by("-invoice_date", "-id")
        )
        today = timezone.localdate()

        # Status filter
        status = self.request.GET.get("status", "").strip().lower()
        if status == "overdue":
            qs = qs.filter(status=InvoiceStatus.CONFIRMED, due_date__lt=today, amount_paid__lt=F("total"))
        elif status in ("partially_paid", "partially paid"):
            qs = qs.filter(status=InvoiceStatus.CONFIRMED, amount_paid__gt=0, amount_paid__lt=F("total"))
        elif status in [s.value for s in InvoiceStatus]:
            qs = qs.filter(status=status)

        # Date range filters
        date_from = self.request.GET.get("date_from", "").strip()
        if date_from:
            qs = qs.filter(invoice_date__gte=date_from)

        date_to = self.request.GET.get("date_to", "").strip()
        if date_to:
            qs = qs.filter(invoice_date__lte=date_to)

        # Customer search filter
        customer_q = (self.request.GET.get("customer") or self.request.GET.get("q", "")).strip()
        if customer_q:
            qs = qs.filter(
                Q(customer__name__icontains=customer_q) |
                Q(customer__user__email__icontains=customer_q) |
                Q(number__icontains=customer_q)
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()

        ctx["filters"] = {
            "status": self.request.GET.get("status", ""),
            "date_from": self.request.GET.get("date_from", ""),
            "date_to": self.request.GET.get("date_to", ""),
            "customer": self.request.GET.get("customer") or self.request.GET.get("q", ""),
            "q": self.request.GET.get("customer") or self.request.GET.get("q", ""),
        }
        ctx["today"] = today
        return ctx


class InvoiceDetailView(View):
    """
    Detailed invoice view including frozen lines, payments, tax breakdown,
    and the 'Why this amount?' calculation panel.
    Enforces tenant isolation: customer can only view invoices belonging to their account.
    """
    def get(self, request, identifier, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.conf import settings
            from django.shortcuts import redirect
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")

        # Lookup by integer pk or invoice number string
        invoice_qs = (
            Invoice.objects.select_related("customer", "subscription", "customer__user")
            .prefetch_related("lines__product", "lines__discount", "payments__recorded_by")
        )
        if str(identifier).isdigit():
            invoice = invoice_qs.filter(Q(pk=int(identifier)) | Q(number=str(identifier))).first()
        else:
            invoice = invoice_qs.filter(number=str(identifier)).first()

        if not invoice:
            raise Http404("Invoice not found.")

        # Access control: staff/admin can view all; customer can only view own invoice
        user_role = getattr(request.user, "role", None)
        if not (request.user.is_superuser or user_role in ("admin", "staff")):
            # Check customer ownership
            customer = getattr(request.user, "customer_profile", None)
            if not customer or invoice.customer_id != customer.id:
                raise PermissionDenied("You do not have permission to view another customer's invoice.")

        breakdown = get_invoice_calculation_breakdown(invoice)
        balance = max(Decimal("0.00"), invoice.total - invoice.amount_paid)

        context = {
            "invoice": invoice,
            "lines": invoice.lines.all().select_related("product", "discount"),
            "payments": invoice.payments.all().order_by("-paid_on", "-id"),
            "breakdown": breakdown,
            "tax_groups": breakdown.get("tax_groups", []),
            "balance": balance,
            "today": timezone.localdate(),
        }
        return render(request, "billing/invoice_detail.html", context)


class InvoicePrintView(View):
    """
    Print-friendly A4 invoice view rendering invoice_print.html.
    Accessible to staff, admin, and the invoice owner.
    """
    def get(self, request, identifier, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.conf import settings
            from django.shortcuts import redirect
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")

        invoice_qs = (
            Invoice.objects.select_related("customer", "subscription", "customer__user")
            .prefetch_related("lines__product", "lines__discount", "payments")
        )
        if str(identifier).isdigit():
            invoice = invoice_qs.filter(Q(pk=int(identifier)) | Q(number=str(identifier))).first()
        else:
            invoice = invoice_qs.filter(number=str(identifier)).first()

        if not invoice:
            raise Http404("Invoice not found.")

        user_role = getattr(request.user, "role", None)
        if not (request.user.is_superuser or user_role in ("admin", "staff")):
            customer = getattr(request.user, "customer_profile", None)
            if not customer or invoice.customer_id != customer.id:
                raise PermissionDenied("You do not have permission to view another customer's invoice.")

        context = {
            "invoice": invoice,
            "today": timezone.localdate(),
        }
        return render(request, "billing/invoice_print.html", context)


# ---------------------------------------------------------------------------
# A6: Billing Run (admin-only) — /billing/run/
# ---------------------------------------------------------------------------

class BillingRunView(RoleRequiredMixin, View):
    """
    Admin-only billing run page.

    GET  → render run.html with empty form (no results yet).
    POST → run billing engine in dry-run (action=preview) or live (action=commit) mode.

    Context passed to run.html:
        billing_run   : BillingRun instance (after POST) or None
        is_preview    : True when the last run was a dry-run preview
        target_as_of  : date string for the date input (defaults to today)
        items         : first 200 BillingRunItems for the breakdown table
        today         : today's date
    """
    allowed_roles = ["admin"]

    def get(self, request, *args, **kwargs):
        today = timezone.localdate()
        return render(request, "billing/run.html", {
            "billing_run": None,
            "is_preview": False,
            "target_as_of": today.isoformat(),
            "items": [],
            "today": today,
        })

    def post(self, request, *args, **kwargs):
        from apps.billing.services.billing_run import run_billing

        today = timezone.localdate()
        action = request.POST.get("action", "preview")
        as_of_str = request.POST.get("as_of", "").strip()

        # Parse as_of date; fall back to today
        try:
            from datetime import date
            as_of = date.fromisoformat(as_of_str) if as_of_str else today
        except ValueError:
            as_of = today

        dry_run = action != "commit"
        billing_run = run_billing(as_of=as_of, dry_run=dry_run, user=request.user)

        # Fetch first 200 items for the detailed table
        items = (
            billing_run.items.select_related("subscription__customer", "invoice")
            .order_by("id")[:200]
        ) if not dry_run else []

        return render(request, "billing/run.html", {
            "billing_run": billing_run,
            "is_preview": dry_run,
            "target_as_of": as_of.isoformat(),
            "items": items,
            "today": today,
        })


# ---------------------------------------------------------------------------
# A6: Coverage Check (admin-only) — /billing/coverage/
# ---------------------------------------------------------------------------

class BillingCoverageView(RoleRequiredMixin, View):
    """
    Admin-only billing coverage / integrity dashboard.

    Context passed to coverage.html:
        unbilled_count      : active non-paused subs with next_invoice_date <= today
        duplicate_count     : invoice groups sharing (subscription, period_start)
        unbilled_subs       : first 50 unbilled Subscription objects (for diagnostic table)
        as_of               : today's date
        today               : today's date
    """
    allowed_roles = ["admin"]

    def get(self, request, *args, **kwargs):
        today = timezone.localdate()

        # Check 1: active non-paused subscriptions with unbilled periods due today
        unbilled_qs = Subscription.objects.filter(
            status=SubscriptionStatus.ACTIVE,
            paused_at__isnull=True,
            next_invoice_date__lte=today,
        )
        unbilled_count = unbilled_qs.count()
        unbilled_subs = list(
            unbilled_qs.select_related("customer", "plan").order_by("next_invoice_date")[:50]
        )

        # Check 2: duplicate invoices per (subscription, period_start)
        duplicate_count = (
            Invoice.objects
            .values("subscription_id", "period_start")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .count()
        )

        return render(request, "billing/coverage.html", {
            "unbilled_count": unbilled_count,
            "duplicate_count": duplicate_count,
            "unbilled_subs": unbilled_subs,
            "as_of": today,
            "today": today,
        })
