from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, View

from apps.accounts.permissions import RoleRequiredMixin
from apps.catalog.forms import (
    ProductForm,
    ProductVariantFormSet,
    PlanForm,
    TaxForm,
    DiscountForm,
)
from apps.catalog.models import Product, Plan, Tax, Discount


# ==========================================
# Products
# ==========================================

class ProductListView(RoleRequiredMixin, ListView):
    model = Product
    template_name = "catalog/product_list.html"
    context_object_name = "products"
    paginate_by = 25

    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        qs = Product.objects.all().select_related("tax").prefetch_related("variants")
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(notes__icontains=query))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["can_write"] = self.request.user.role == "admin" or self.request.user.is_superuser
        return ctx


class ProductCreateView(RoleRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = "catalog/product_form.html"
    success_url = reverse_lazy("catalog:product_list")
    allowed_roles = ["admin"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["variant_formset"] = ProductVariantFormSet(self.request.POST, prefix="variants")
        else:
            ctx["variant_formset"] = ProductVariantFormSet(prefix="variants")
        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        variant_formset = context["variant_formset"]
        with transaction.atomic():
            self.object = form.save()
            if variant_formset.is_valid():
                variant_formset.instance = self.object
                variant_formset.save()
            else:
                return self.form_invalid(form)
        messages.success(self.request, f'Product "{self.object.name}" created successfully.')
        return redirect(self.get_success_url())


class ProductUpdateView(RoleRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "catalog/product_form.html"
    success_url = reverse_lazy("catalog:product_list")
    allowed_roles = ["admin"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["variant_formset"] = ProductVariantFormSet(self.request.POST, instance=self.object, prefix="variants")
        else:
            ctx["variant_formset"] = ProductVariantFormSet(instance=self.object, prefix="variants")
        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        variant_formset = context["variant_formset"]
        with transaction.atomic():
            self.object = form.save()
            if variant_formset.is_valid():
                variant_formset.instance = self.object
                variant_formset.save()
            else:
                return self.form_invalid(form)
        messages.success(self.request, f'Product "{self.object.name}" updated successfully.')
        return redirect(self.get_success_url())


class ProductDeleteView(RoleRequiredMixin, View):
    allowed_roles = ["admin"]

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.is_active = False
        product.save(update_fields=["is_active"])
        messages.success(request, f'Product "{product.name}" was deactivated.')
        return redirect("catalog:product_list")


# ==========================================
# Plans
# ==========================================

class PlanListView(RoleRequiredMixin, ListView):
    model = Plan
    template_name = "catalog/plan_list.html"
    context_object_name = "plans"
    paginate_by = 25
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        qs = Plan.objects.all()
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(name__icontains=query)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["can_write"] = self.request.user.role == "admin" or self.request.user.is_superuser
        return ctx


class PlanCreateView(RoleRequiredMixin, CreateView):
    model = Plan
    form_class = PlanForm
    template_name = "catalog/plan_form.html"
    success_url = reverse_lazy("catalog:plan_list")
    allowed_roles = ["admin"]

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Plan "{self.object.name}" created successfully.')
        return response


class PlanUpdateView(RoleRequiredMixin, UpdateView):
    model = Plan
    form_class = PlanForm
    template_name = "catalog/plan_form.html"
    success_url = reverse_lazy("catalog:plan_list")
    allowed_roles = ["admin"]

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Plan "{self.object.name}" updated successfully.')
        return response


class PlanDeleteView(RoleRequiredMixin, View):
    allowed_roles = ["admin"]

    def post(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        plan.delete()
        messages.success(request, f'Plan "{plan.name}" deleted.')
        return redirect("catalog:plan_list")


# ==========================================
# Taxes
# ==========================================

class TaxListView(RoleRequiredMixin, ListView):
    model = Tax
    template_name = "catalog/tax_list.html"
    context_object_name = "taxes"
    paginate_by = 25
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        qs = Tax.objects.all()
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(name__icontains=query)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["can_write"] = self.request.user.role == "admin" or self.request.user.is_superuser
        return ctx


class TaxCreateView(RoleRequiredMixin, CreateView):
    model = Tax
    form_class = TaxForm
    template_name = "catalog/tax_form.html"
    success_url = reverse_lazy("catalog:tax_list")
    allowed_roles = ["admin"]

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Tax "{self.object.name}" created successfully.')
        return response


class TaxUpdateView(RoleRequiredMixin, UpdateView):
    model = Tax
    form_class = TaxForm
    template_name = "catalog/tax_form.html"
    success_url = reverse_lazy("catalog:tax_list")
    allowed_roles = ["admin"]

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Tax "{self.object.name}" updated successfully.')
        return response


# ==========================================
# Discounts
# ==========================================

class DiscountListView(RoleRequiredMixin, ListView):
    model = Discount
    template_name = "catalog/discount_list.html"
    context_object_name = "discounts"
    paginate_by = 25
    allowed_roles = ["admin", "staff"]

    def get_queryset(self):
        qs = Discount.objects.all().prefetch_related("products")
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(name__icontains=query)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["can_write"] = self.request.user.role == "admin" or self.request.user.is_superuser
        return ctx


class DiscountCreateView(RoleRequiredMixin, CreateView):
    model = Discount
    form_class = DiscountForm
    template_name = "catalog/discount_form.html"
    success_url = reverse_lazy("catalog:discount_list")
    allowed_roles = ["admin"]

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Discount "{self.object.name}" created successfully.')
        return response


class DiscountUpdateView(RoleRequiredMixin, UpdateView):
    model = Discount
    form_class = DiscountForm
    template_name = "catalog/discount_form.html"
    success_url = reverse_lazy("catalog:discount_list")
    allowed_roles = ["admin"]

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Discount "{self.object.name}" updated successfully.')
        return response


class DiscountDeleteView(RoleRequiredMixin, View):
    allowed_roles = ["admin"]

    def post(self, request, pk):
        discount = get_object_or_404(Discount, pk=pk)
        discount.is_active = False
        discount.save(update_fields=["is_active"])
        messages.success(request, f'Discount "{discount.name}" was deactivated.')
        return redirect("catalog:discount_list")
