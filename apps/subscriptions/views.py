from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from apps.accounts.permissions import RoleRequiredMixin
from apps.core.exceptions import DomainError
from apps.subscriptions.forms import (
    QuotationTemplateForm,
    SubscriptionForm,
    TemplateLineFormSet,
)
from apps.subscriptions.models import (
    QuotationTemplate,
    Subscription,
    SubscriptionEvent,
    SubscriptionLine,
    SubscriptionStatus,
)
from apps.subscriptions.services import lifecycle
from apps.catalog.models import Plan


class SubscriptionListView(RoleRequiredMixin, ListView):
    """
    Paginated list of subscriptions for admin and staff.
    Supports filtering by status, customer, and text search.
    """
    model = Subscription
    template_name = "subscriptions/subscription_list.html"
    context_object_name = "subscriptions"
    paginate_by = 25
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        qs = (
            Subscription.objects.select_related("customer", "plan", "created_by")
            .order_by("-id")
        )

        status = self.request.GET.get("status", "").strip().lower()
        if status in [s.value for s in SubscriptionStatus]:
            qs = qs.filter(status=status)
        elif status == "paused":
            qs = qs.filter(paused_at__isnull=False)

        plan_id = self.request.GET.get("plan", "").strip()
        if plan_id:
            qs = qs.filter(plan_id=plan_id)

        q = (self.request.GET.get("q") or self.request.GET.get("customer", "")).strip()
        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(customer__name__icontains=q)
                | Q(customer__user__email__icontains=q)
            )

        # Sorting support: date, customer, amount
        sort = self.request.GET.get("sort", "-id").strip()
        sort_map = {
            "date_asc": "start_date",
            "date_desc": "-start_date",
            "customer_asc": "customer__name",
            "customer_desc": "-customer__name",
            "amount_asc": "plan__price",
            "amount_desc": "-plan__price",
        }
        order_field = sort_map.get(sort, "-id")
        return qs.order_by(order_field)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = SubscriptionStatus.choices
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["current_plan"] = self.request.GET.get("plan", "")
        ctx["current_sort"] = self.request.GET.get("sort", "")
        ctx["plans"] = Plan.objects.all().order_by("name")
        ctx["search_query"] = self.request.GET.get("q") or self.request.GET.get("customer", "")
        return ctx


class SubscriptionDetailView(RoleRequiredMixin, DetailView):
    """
    Comprehensive subscription detail view:
      - Header & status stepper
      - Frozen line items with plan fee
      - Audit timeline from SubscriptionEvent
      - Transition action buttons gated by status and plan flags
    """
    model = Subscription
    template_name = "subscriptions/subscription_detail.html"
    context_object_name = "subscription"
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        return Subscription.objects.select_related("customer", "plan", "created_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sub = self.object
        today = timezone.localdate()

        lines = list(sub.lines.select_related("product", "variant").all())
        events = sub.events.select_related("actor").order_by("-created_at")

        # Invoices for this subscription
        invoices = sub.invoices.all().order_by("-invoice_date", "-id")

        ctx["lines"] = lines
        ctx["events"] = events
        ctx["invoices"] = invoices
        ctx["today"] = today
        ctx["is_quote_expired"] = sub.is_quote_expired(today)

        # Precompute allowed transitions for UI action buttons
        plan = sub.plan
        actions = []
        if sub.status == SubscriptionStatus.DRAFT:
            actions.append("to_quotation")
        elif sub.status == SubscriptionStatus.QUOTATION:
            if not sub.is_quote_expired(today):
                actions.append("confirm")
        elif sub.status == SubscriptionStatus.CONFIRMED:
            actions.append("activate")
        elif sub.status == SubscriptionStatus.ACTIVE:
            if sub.is_paused:
                actions.append("resume")
            else:
                if plan.allow_pause:
                    actions.append("pause")
                actions.append("generate_invoice")
            if plan.allow_renew:
                actions.append("renew")
            if plan.allow_early_close:
                actions.append("close")

        ctx["allowed_actions"] = actions
        return ctx


class SubscriptionCreateView(RoleRequiredMixin, View):
    """
    Create a new subscription from scratch or populate lines from a QuotationTemplate.
    """
    allowed_roles = ["admin", "staff"]

    def get(self, request):
        initial = {}
        template_id = request.GET.get("template")
        if template_id:
            try:
                tmpl = QuotationTemplate.objects.filter(pk=template_id, is_active=True).first()
                if tmpl:
                    initial["template"] = tmpl
                    initial["plan"] = tmpl.plan_id
            except (ValueError, TypeError):
                pass
        form = SubscriptionForm(initial=initial)
        return render(request, "subscriptions/subscription_form.html", {"form": form})

    def post(self, request):
        form = SubscriptionForm(request.POST)
        if form.is_valid():
            template = form.cleaned_data.get("template")
            customer = form.cleaned_data["customer"]
            start_date = form.cleaned_data["start_date"]
            expiry_date = form.cleaned_data.get("expiry_date")
            plan = form.cleaned_data["plan"]
            terms = form.cleaned_data.get("payment_terms_days", 15)

            if template:
                sub = lifecycle.create_from_template(
                    template=template,
                    customer=customer,
                    start_date=start_date,
                    user=request.user,
                )
                if expiry_date:
                    sub.expiry_date = expiry_date
                sub.payment_terms_days = terms
                sub.save()
            else:
                sub = lifecycle.create_subscription(
                    customer=customer,
                    plan=plan,
                    start_date=start_date,
                    expiry_date=expiry_date,
                    payment_terms_days=terms,
                    user=request.user,
                )

            messages.success(request, f"Subscription {sub.number} successfully created!")
            return redirect(f"/subscriptions/{sub.id}/")

        return render(request, "subscriptions/subscription_form.html", {"form": form})


class SubscriptionTransitionView(RoleRequiredMixin, View):
    """
    Handles POST action triggers for subscription state transitions:
    to_quotation, confirm, activate, pause, resume, renew, close.
    """
    allowed_roles = ["admin", "staff"]

    def post(self, request, pk, action):
        sub = get_object_or_404(Subscription, pk=pk)
        today = timezone.localdate()

        try:
            if action == "to_quotation":
                lifecycle.to_quotation(sub, actor=request.user, today=today)
                messages.success(request, f"Subscription {sub.number} transitioned to Quotation.")
            elif action == "confirm":
                lifecycle.confirm(sub, actor=request.user, today=today)
                messages.success(request, f"Quotation {sub.number} confirmed.")
            elif action == "activate":
                lifecycle.activate(sub, actor=request.user)
                messages.success(request, f"Subscription {sub.number} activated and billing initialized.")
            elif action == "pause":
                lifecycle.pause(sub, actor=request.user, today=today)
                messages.warning(request, f"Subscription {sub.number} paused.")
            elif action == "resume":
                lifecycle.resume(sub, actor=request.user, today=today)
                messages.success(request, f"Subscription {sub.number} resumed and re-anchored.")
            elif action == "renew":
                lifecycle.renew(sub, actor=request.user)
                messages.success(request, f"Subscription {sub.number} renewed.")
            elif action == "close":
                lifecycle.close(sub, actor=request.user)
                messages.info(request, f"Subscription {sub.number} closed.")
            elif action == "generate_invoice":
                from apps.billing.services.invoicing import generate_invoice_for_subscription
                inv = generate_invoice_for_subscription(sub)
                messages.success(request, f"Invoice {inv.number or inv.id} generated directly from subscription {sub.number}.")
                return redirect(f"/invoices/{inv.number or inv.id}/")
            else:
                messages.error(request, f"Unknown lifecycle action: {action}")
        except DomainError as err:
            messages.error(request, str(err))
        except Exception as exc:
            messages.error(request, f"Transition failed: {exc}")

        return redirect(f"/subscriptions/{sub.id}/")


# ---------------------------------------------------------------------------
# Quotation Templates CRUD
# ---------------------------------------------------------------------------

class QuotationTemplateListView(RoleRequiredMixin, ListView):
    model = QuotationTemplate
    template_name = "subscriptions/template_list.html"
    context_object_name = "templates"
    allowed_roles = ["admin", "staff"]
    paginate_by = 25

    def get_queryset(self):
        return QuotationTemplate.objects.select_related("plan").order_by("-is_active", "name")


class QuotationTemplateCreateView(RoleRequiredMixin, View):
    allowed_roles = ["admin", "staff"]

    def get(self, request):
        form = QuotationTemplateForm()
        formset = TemplateLineFormSet()
        return render(request, "subscriptions/template_form.html", {"form": form, "formset": formset})

    def post(self, request):
        form = QuotationTemplateForm(request.POST)
        formset = TemplateLineFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            template = form.save()
            formset.instance = template
            formset.save()
            messages.success(request, f"Template '{template.name}' created successfully.")
            return redirect("/templates/")

        return render(request, "subscriptions/template_form.html", {"form": form, "formset": formset})


class QuotationTemplateDetailView(RoleRequiredMixin, DetailView):
    model = QuotationTemplate
    template_name = "subscriptions/template_detail.html"
    context_object_name = "template"
    allowed_roles = ["admin", "staff"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lines"] = self.object.lines.select_related("product", "variant").all()
        return ctx


class QuotationTemplateDeleteView(RoleRequiredMixin, DeleteView):
    model = QuotationTemplate
    template_name = "subscriptions/template_confirm_delete.html"
    success_url = reverse_lazy("subscriptions:template_list")
    allowed_roles = ["admin"]
