from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.accounts.urls')),
    path('', include('apps.catalog.urls')),
    path('invoices/', include('apps.billing.urls')),
    path('portal/', include('apps.portal.urls')),
    path('reports/', include('apps.reports.urls')),
]
