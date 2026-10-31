from django.urls import path, re_path
from apps.billing import views

app_name = "billing"

urlpatterns = [
    path("", views.InvoiceListView.as_view(), name="invoice_list"),
    re_path(r"^(?P<identifier>[\w-]+)/print/$", views.InvoicePrintView.as_view(), name="invoice_print"),
    re_path(r"^(?P<identifier>[\w-]+)/$", views.InvoiceDetailView.as_view(), name="invoice_detail"),
]
