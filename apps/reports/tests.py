from django.test import SimpleTestCase, RequestFactory
from django.core.exceptions import PermissionDenied
from apps.reports.views import dashboard_view
from apps.reports.services import get_summary


class MockUser:
    def __init__(self, email, role, is_authenticated=True, is_superuser=False):
        self.email = email
        self.role = role
        self.is_authenticated = is_authenticated
        self.is_superuser = is_superuser


class ReportsDashboardTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.staff_user = MockUser("staff@brightloop.test", role="staff")
        self.admin_user = MockUser("admin@brightloop.test", role="admin")
        self.customer_user = MockUser("customer@brightloop.test", role="customer")

    def test_dashboard_renders_200_for_staff(self):
        request = self.factory.get("/reports/")
        request.user = self.staff_user
        response = dashboard_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Finance & Revenue Dashboard", html=False)
        self.assertContains(response, "Monthly Recurring Revenue", html=False)

    def test_dashboard_renders_200_for_admin(self):
        request = self.factory.get("/reports/")
        request.user = self.admin_user
        response = dashboard_view(request)
        self.assertEqual(response.status_code, 200)

    def test_dashboard_renders_403_for_customer(self):
        request = self.factory.get("/reports/")
        request.user = self.customer_user
        with self.assertRaises(PermissionDenied):
            dashboard_view(request)

    def test_filter_parameters_preserved_in_context_and_form(self):
        params = {
            "date_from": "2026-10-01",
            "date_to": "2026-10-31",
            "status": "active",
            "customer": "Acme",
        }
        request = self.factory.get("/reports/", params)
        request.user = self.staff_user
        response = dashboard_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="2026-10-01"')
        self.assertContains(response, 'value="2026-10-31"')
        self.assertContains(response, 'value="Acme"')
        self.assertContains(response, 'selected>Active</option>')

    def test_get_summary_contract_shape(self):
        summary = get_summary()
        required_keys = [
            "active_subscriptions",
            "paused_subscriptions",
            "revenue_collected",
            "billed",
            "outstanding",
            "overdue_count",
            "overdue_amount",
            "mrr",
            "arr",
            "ageing",
            "recent_payments",
            "overdue_invoices",
        ]
        for key in required_keys:
            self.assertIn(key, summary)

        self.assertIn("1-30", summary["ageing"])
        self.assertIn("31-60", summary["ageing"])
        self.assertIn("60+", summary["ageing"])
