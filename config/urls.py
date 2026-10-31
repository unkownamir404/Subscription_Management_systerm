from django.contrib import admin
from django.urls import path, include
from apps.billing.urls import billing_engine_urlpatterns
from apps.subscriptions.views import QuotationTemplateListView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.accounts.urls')),
    path('', include('apps.catalog.urls')),
    path('subscriptions/', include('apps.subscriptions.urls')),
    path('templates/', QuotationTemplateListView.as_view(), name='quotation_templates_root'),
    path('invoices/', include('apps.billing.urls')),
    path('billing/', include((billing_engine_urlpatterns, 'billing_engine'))),
    path('portal/', include('apps.portal.urls')),
    path('reports/', include('apps.reports.urls')),
]
