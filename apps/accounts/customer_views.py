from django.views.generic import ListView, DetailView, UpdateView, CreateView
from django.db.models import Q, Count, Sum
from django.urls import reverse_lazy
from django.contrib import messages
from apps.accounts.models import Customer
from apps.accounts.permissions import RoleRequiredMixin
from apps.billing.models import Invoice, Payment
from apps.subscriptions.models import Subscription, SubscriptionStatus


class CustomerListView(RoleRequiredMixin, ListView):
    """
    Searchable, paginated customer list for Staff and Admin.
    Shows active subscriptions count, total spent, and outstanding balance.
    """
    allowed_roles = ["admin", "staff"]
    model = Customer
    template_name = "accounts/customer_list.html"
    context_object_name = "customers"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Customer.objects.select_related("user")
            .annotate(
                active_subs_count=Count(
                    "subscriptions",
                    filter=Q(subscriptions__status=SubscriptionStatus.ACTIVE),
                    distinct=True,
                ),
                total_invoices_count=Count("invoices", distinct=True),
            )
            .order_by("-created_at")
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(company__icontains=q)
                | Q(user__email__icontains=q)
                | Q(phone__icontains=q)
                | Q(tax_id__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["query"] = self.request.GET.get("q", "")
        ctx["total_customers"] = Customer.objects.count()
        return ctx


class CustomerDetailView(RoleRequiredMixin, DetailView):
    """
    Detailed customer profile with subscription contracts, invoices, and payment history.
    """
    allowed_roles = ["admin", "staff"]
    model = Customer
    template_name = "accounts/customer_detail.html"
    context_object_name = "customer"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        customer = self.object

        subscriptions = (
            customer.subscriptions.select_related("plan")
            .prefetch_related("lines__product")
            .order_by("-created_at")
        )
        invoices = (
            customer.invoices.select_related("subscription")
            .order_by("-invoice_date")
        )
        payments = (
            Payment.objects.filter(invoice__customer=customer)
            .select_related("invoice")
            .order_by("-paid_on")
        )

        total_billed = invoices.aggregate(s=Sum("total"))["s"] or 0
        total_paid = invoices.aggregate(s=Sum("amount_paid"))["s"] or 0
        outstanding = total_billed - total_paid

        ctx["subscriptions"] = subscriptions
        ctx["invoices"] = invoices
        ctx["payments"] = payments
        ctx["total_billed"] = total_billed
        ctx["total_paid"] = total_paid
        ctx["outstanding"] = outstanding
        return ctx


class CustomerUpdateView(RoleRequiredMixin, UpdateView):
    """
    Update customer profile details.
    """
    allowed_roles = ["admin", "staff"]
    model = Customer
    template_name = "accounts/customer_form.html"
    fields = ["name", "company", "phone", "billing_address", "tax_id"]

    def get_success_url(self):
        messages.success(self.request, f"Customer {self.object.name} updated successfully.")
        return reverse_lazy("customer_detail", kwargs={"pk": self.object.pk})


class CustomerCreateView(RoleRequiredMixin, CreateView):
    """
    Create a new customer profile.
    """
    allowed_roles = ["admin", "staff"]
    model = Customer
    template_name = "accounts/customer_form.html"
    fields = ["name", "company", "phone", "billing_address", "tax_id"]

    def get_success_url(self):
        messages.success(self.request, f"Customer {self.object.name} created successfully.")
        return reverse_lazy("customer_detail", kwargs={"pk": self.object.pk})
