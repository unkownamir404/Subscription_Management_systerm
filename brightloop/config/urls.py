from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse

def placeholder_home(request):
    return HttpResponse("<h1>Brightloop Subscription Management System</h1><p>MVP Scaffold is running.</p>")

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.accounts.urls')),
    path('', include('apps.catalog.urls')),
    path('', include('apps.subscriptions.urls')),
    path('portal/', include('apps.portal.urls')),
    path('', placeholder_home, name='home'),
]
