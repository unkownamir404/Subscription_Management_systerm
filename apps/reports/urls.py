from django.urls import path
from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("financial/", views.financial_reports_view, name="financial_summary"),
    path("export/", views.export_report_csv_view, name="export_csv"),
    path("api/summary/", views.summary_api_view, name="api_summary"),
]
