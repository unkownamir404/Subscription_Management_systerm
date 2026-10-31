from django.urls import path, re_path
from apps.portal import views

app_name = "portal"

urlpatterns = [
    path("", views.portal_dashboard, name="dashboard"),
    path("subscriptions/", views.portal_subscriptions, name="subscriptions"),
    path("subscriptions/<int:subscription_id>/pause/", views.portal_subscription_pause, name="subscription_pause"),
    path("subscriptions/<int:subscription_id>/renew/", views.portal_subscription_renew, name="subscription_renew"),
    path("invoices/", views.portal_invoices, name="invoices"),
    re_path(r"^invoices/(?P<identifier>[\w-]+)/pay/$", views.portal_invoice_pay, name="invoice_pay"),
]
