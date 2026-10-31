from django.urls import path
from apps.portal.views import portal_dashboard

app_name = 'portal'

urlpatterns = [
    path('', portal_dashboard, name='dashboard'),
]
