from django.urls import path
from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("api/summary/", views.summary_api_view, name="api_summary"),
]
