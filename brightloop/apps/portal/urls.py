from django.urls import path
from apps.portal import views

app_name = "portal"

urlpatterns = [
    path("", views.PortalDashboardView.as_view(), name="dashboard"),
    path("subscriptions/", views.PortalSubscriptionListView.as_view(), name="subscription_list"),
    path("subscriptions/<int:pk>/", views.PortalSubscriptionDetailView.as_view(), name="subscription_detail"),
    path("subscriptions/<int:pk>/<str:action>/", views.PortalSubscriptionActionView.as_view(), name="subscription_action"),
    path("invoices/", views.PortalInvoiceListView.as_view(), name="invoice_list"),
    path("invoices/<int:pk>/", views.PortalInvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoices/<int:pk>/pay/", views.PortalPayInvoiceView.as_view(), name="pay_invoice"),
]
