from datetime import timedelta
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View, FormView

from apps.accounts.permissions import RoleRequiredMixin
from apps.billing.services.pricing import line_unit_price
from apps.catalog.models import Plan, Product, Tax
from apps.subscriptions.forms import (
    SubscriptionForm,
    SubscriptionLineFormSet,
    QuotationTemplateForm,
    TemplateLineFormSet,
    QuotationFromTemplateForm,
)
from apps.subscriptions.models import (
    Subscription,
    SubscriptionLine,
    SubscriptionEvent,
    QuotationTemplate,
)
from apps.subscriptions.services import transitions


# ==========================================
# Subscriptions
# ==========================================

class SubscriptionListView(RoleRequiredMixin, ListView):
    model = Subscription
    template_name = "subscriptions/subscription_list.html"
    context_object_name = "subscriptions"
    paginate_by = 25
    # Customers access subscriptions via /portal/ only; staff-side views are admin/staff.
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        qs = Subscription.objects.for_user(self.request.user).select_related("customer", "plan")

        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)

        plan_id = self.request.GET.get("plan")
        if plan_id:
            qs = qs.filter(plan_id=plan_id)

        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(number__icontains=query)
                | Q(customer__name__icontains=query)
                | Q(customer__company__icontains=query)
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = Subscription.Status.choices
        ctx["plans"] = Plan.objects.all()
        ctx["selected_status"] = self.request.GET.get("status", "")
        ctx["selected_plan"] = self.request.GET.get("plan", "")
        ctx["q"] = self.request.GET.get("q", "")
        ctx["can_write"] = self.request.user.role in ("admin", "staff") or self.request.user.is_superuser
        return ctx


class SubscriptionDetailView(RoleRequiredMixin, DetailView):
    model = Subscription
    template_name = "subscriptions/subscription_detail.html"
    context_object_name = "subscription"
    # Customers access subscriptions via /portal/ only; staff-side views are admin/staff.
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        # Cross-customer access will return 404 because of for_user() scoping
        return (
            Subscription.objects.for_user(self.request.user)
            .select_related("customer", "plan", "created_by")
            .prefetch_related("lines__product__tax", "lines__variant", "events__actor")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sub = self.object
        lines = sub.lines.all()

        subtotal = sum((line.line_subtotal for line in lines), Decimal("0.00"))
        tax_total = sum((line.line_tax for line in lines), Decimal("0.00"))
        total = subtotal + tax_total

        ctx["lines"] = lines
        ctx["subtotal"] = subtotal
        ctx["tax_total"] = tax_total
        ctx["total"] = total
        ctx["events"] = sub.events.all()
        ctx["can_manage"] = self.request.user.role in ("admin", "staff") or self.request.user.is_superuser
        return ctx


class SubscriptionCreateView(RoleRequiredMixin, CreateView):
    model = Subscription
    form_class = SubscriptionForm
    template_name = "subscriptions/subscription_form.html"
    allowed_roles = ["admin", "staff"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["line_formset"] = SubscriptionLineFormSet(self.request.POST, prefix="lines")
        else:
            ctx["line_formset"] = SubscriptionLineFormSet(prefix="lines")
        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        line_formset = context["line_formset"]

        with transaction.atomic():
            self.object = form.save(commit=False)
            self.object.created_by = self.request.user
            self.object.status = Subscription.Status.DRAFT
            self.object.save()

            if line_formset.is_valid():
                line_formset.instance = self.object
                line_formset.save()
            else:
                return self.form_invalid(form)

            SubscriptionEvent.objects.create(
                subscription=self.object,
                from_status="",
                to_status=self.object.status,
                action="create",
                actor=self.request.user,
                note="Subscription created in draft status.",
            )

        messages.success(self.request, f"Subscription {self.object.number} created successfully.")
        return redirect(reverse("subscriptions:subscription_detail", kwargs={"pk": self.object.pk}))


class SubscriptionUpdateView(RoleRequiredMixin, UpdateView):
    model = Subscription
    form_class = SubscriptionForm
    template_name = "subscriptions/subscription_form.html"
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        return Subscription.objects.for_user(self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["line_formset"] = SubscriptionLineFormSet(self.request.POST, instance=self.object, prefix="lines")
        else:
            ctx["line_formset"] = SubscriptionLineFormSet(instance=self.object, prefix="lines")
        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        line_formset = context["line_formset"]

        with transaction.atomic():
            self.object = form.save()
            if line_formset.is_valid():
                line_formset.instance = self.object
                line_formset.save()
            else:
                return self.form_invalid(form)

        messages.success(self.request, f"Subscription {self.object.number} updated successfully.")
        return redirect(reverse("subscriptions:subscription_detail", kwargs={"pk": self.object.pk}))


# ==========================================
# State Machine Action Views (POST only)
# ==========================================

class SubscriptionTransitionView(RoleRequiredMixin, View):
    allowed_roles = ["admin", "staff"]
    action_name = None

    def post(self, request, pk):
        subscription = get_object_or_404(Subscription.objects.for_user(request.user), pk=pk)
        note = request.POST.get("note", "").strip()

        action_map = {
            "quotation": transitions.mark_as_quotation,
            "confirm": transitions.confirm_subscription,
            "activate": transitions.activate_subscription,
            "pause": transitions.pause_subscription,
            "resume": transitions.resume_subscription,
            "close": transitions.close_subscription,
            "renew": transitions.renew_subscription,
        }

        func = action_map.get(self.action_name)
        if not func:
            messages.error(request, f"Unknown action: {self.action_name}")
            return redirect("subscriptions:subscription_detail", pk=pk)

        try:
            func(subscription, user=request.user, note=note)
            messages.success(request, f'Subscription action "{self.action_name}" completed successfully.')
        except ValidationError as exc:
            for error in exc.messages if hasattr(exc, "messages") else [str(exc)]:
                messages.error(request, error)

        return redirect("subscriptions:subscription_detail", pk=pk)


# ==========================================
# Quotation Templates
# ==========================================

class QuotationTemplateListView(RoleRequiredMixin, ListView):
    model = QuotationTemplate
    template_name = "subscriptions/template_list.html"
    context_object_name = "templates"
    paginate_by = 25
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        return QuotationTemplate.objects.all().select_related("plan").prefetch_related("lines__product")


class QuotationTemplateCreateView(RoleRequiredMixin, CreateView):
    model = QuotationTemplate
    form_class = QuotationTemplateForm
    template_name = "subscriptions/template_form.html"
    success_url = reverse_lazy("subscriptions:template_list")
    allowed_roles = ["admin", "staff"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["line_formset"] = TemplateLineFormSet(self.request.POST, prefix="lines")
        else:
            ctx["line_formset"] = TemplateLineFormSet(prefix="lines")
        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        line_formset = context["line_formset"]
        with transaction.atomic():
            self.object = form.save()
            if line_formset.is_valid():
                line_formset.instance = self.object
                line_formset.save()
            else:
                return self.form_invalid(form)
        messages.success(self.request, f'Template "{self.object.name}" created.')
        return redirect(self.get_success_url())


class QuotationTemplateUpdateView(RoleRequiredMixin, UpdateView):
    model = QuotationTemplate
    form_class = QuotationTemplateForm
    template_name = "subscriptions/template_form.html"
    success_url = reverse_lazy("subscriptions:template_list")
    allowed_roles = ["admin", "staff"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["line_formset"] = TemplateLineFormSet(self.request.POST, instance=self.object, prefix="lines")
        else:
            ctx["line_formset"] = TemplateLineFormSet(instance=self.object, prefix="lines")
        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        line_formset = context["line_formset"]
        with transaction.atomic():
            self.object = form.save()
            if line_formset.is_valid():
                line_formset.instance = self.object
                line_formset.save()
            else:
                return self.form_invalid(form)
        messages.success(self.request, f'Template "{self.object.name}" updated.')
        return redirect(self.get_success_url())


class QuotationFromTemplateView(RoleRequiredMixin, FormView):
    form_class = QuotationFromTemplateForm
    template_name = "subscriptions/create_from_template.html"
    allowed_roles = ["admin", "staff"]

    def form_valid(self, form):
        template = form.cleaned_data["template"]
        customer = form.cleaned_data["customer"]
        start_date = form.cleaned_data["start_date"]

        # Calculate expiry date from plan interval
        interval = template.plan.interval
        count = template.plan.interval_count
        interval_map = {
            "daily": relativedelta(days=count),
            "weekly": relativedelta(weeks=count),
            "monthly": relativedelta(months=count),
            "yearly": relativedelta(years=count),
        }
        delta = interval_map.get(interval, relativedelta(months=count))
        expiry_date = start_date + delta

        valid_until = start_date + timedelta(days=template.validity_days)

        with transaction.atomic():
            subscription = Subscription.objects.create(
                customer=customer,
                plan=template.plan,
                status=Subscription.Status.QUOTATION,
                start_date=start_date,
                expiry_date=expiry_date,
                quote_valid_until=valid_until,
                created_by=self.request.user,
            )

            # Copy lines and snapshot pricing
            default_tax = Tax.objects.filter(is_default=True).first()
            for t_line in template.lines.all():
                unit_price = line_unit_price(t_line.product, t_line.variant, template.plan)
                tax_rate = (
                    t_line.product.tax.rate
                    if t_line.product.tax
                    else (default_tax.rate if default_tax else Decimal("0.00"))
                )

                SubscriptionLine.objects.create(
                    subscription=subscription,
                    product=t_line.product,
                    variant=t_line.variant,
                    quantity=t_line.quantity,
                    unit_price=unit_price,
                    tax_rate=tax_rate,
                )

            SubscriptionEvent.objects.create(
                subscription=subscription,
                from_status="",
                to_status=subscription.status,
                action="quotation_from_template",
                actor=self.request.user,
                note=f'Quotation created from template "{template.name}".',
            )

        messages.success(self.request, f"Quotation {subscription.number} created from template.")
        return redirect("subscriptions:subscription_detail", pk=subscription.pk)

