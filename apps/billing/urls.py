from django.urls import path, re_path
from apps.billing import views

app_name = "billing"

urlpatterns = [
    path("", views.InvoiceListView.as_view(), name="invoice_list"),
    path("bulk-confirm/", views.InvoiceBulkConfirmView.as_view(), name="invoice_bulk_confirm"),
    re_path(r"^(?P<identifier>[\w-]+)/print/$", views.InvoicePrintView.as_view(), name="invoice_print"),
    re_path(r"^(?P<identifier>[\w-]+)/confirm/$", views.InvoiceConfirmActionView.as_view(), name="invoice_confirm"),
    re_path(r"^(?P<identifier>[\w-]+)/cancel/$", views.InvoiceCancelActionView.as_view(), name="invoice_cancel"),
    re_path(r"^(?P<identifier>[\w-]+)/send/$", views.InvoiceSendActionView.as_view(), name="invoice_send"),
    re_path(r"^(?P<identifier>[\w-]+)/payments/$", views.InvoiceRecordPaymentActionView.as_view(), name="invoice_record_payment"),
    re_path(r"^(?P<identifier>[\w-]+)/$", views.InvoiceDetailView.as_view(), name="invoice_detail"),
]

# Billing engine routes (admin-only) — mounted under /billing/ in config/urls.py
billing_engine_urlpatterns = [
    path("run/", views.BillingRunView.as_view(), name="billing_run"),
    path("coverage/", views.BillingCoverageView.as_view(), name="billing_coverage"),
]
