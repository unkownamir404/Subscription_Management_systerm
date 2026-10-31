"""
Reports service contract for Brightloop Subscription Management System.
Returns summary KPIs, MRR/ARR, aging buckets, overdue invoices, and recent payments.
In C1 this returns a mock contract; in C3 this will be replaced with real DB aggregations.
"""
from decimal import Decimal
from datetime import date


def get_summary(filters=None):
    """
    Returns high-level finance metrics matching the required contract shape.
    """
    filters = filters or {}

    # Hard-coded stub contract for C1
    return {
        "active_subscriptions": 128,
        "paused_subscriptions": 14,
        "revenue_collected": Decimal("485250.00"),
        "billed": Decimal("520000.00"),
        "outstanding": Decimal("34750.00"),
        "overdue_count": 8,
        "overdue_amount": Decimal("18200.00"),
        "mrr": Decimal("425000.00"),
        "arr": Decimal("5100000.00"),
        "ageing": {
            "1-30": Decimal("12000.00"),
            "31-60": Decimal("4500.00"),
            "60+": Decimal("1700.00"),
        },
        "recent_payments": [
            {
                "invoice_number": "INV-2026-000142",
                "customer": "Acme Technologies Pvt Ltd",
                "amount": Decimal("24500.00"),
                "method": "bank_transfer",
                "paid_on": date(2026, 10, 30),
            },
            {
                "invoice_number": "INV-2026-000139",
                "customer": "Zenith Cloud Solutions",
                "amount": Decimal("15000.00"),
                "method": "upi",
                "paid_on": date(2026, 10, 29),
            },
            {
                "invoice_number": "INV-2026-000135",
                "customer": "Nexus Retail Corp",
                "amount": Decimal("38000.00"),
                "method": "card",
                "paid_on": date(2026, 10, 28),
            },
            {
                "invoice_number": "INV-2026-000128",
                "customer": "Apex Logistics",
                "amount": Decimal("9200.00"),
                "method": "cheque",
                "paid_on": date(2026, 10, 27),
            },
            {
                "invoice_number": "INV-2026-000120",
                "customer": "BlueStar Analytics",
                "amount": Decimal("18500.00"),
                "method": "bank_transfer",
                "paid_on": date(2026, 10, 26),
            },
        ],
        "overdue_invoices": [
            {
                "number": "INV-2026-000104",
                "customer": "HyperScale Logistics",
                "due_date": date(2026, 10, 15),
                "balance": Decimal("8500.00"),
                "days_overdue": 16,
            },
            {
                "number": "INV-2026-000098",
                "customer": "Delta Design Studio",
                "due_date": date(2026, 10, 5),
                "balance": Decimal("4200.00"),
                "days_overdue": 26,
            },
            {
                "number": "INV-2026-000085",
                "customer": "Titan Engineering",
                "due_date": date(2026, 9, 20),
                "balance": Decimal("3800.00"),
                "days_overdue": 41,
            },
            {
                "number": "INV-2026-000062",
                "customer": "Vanguard Media",
                "due_date": date(2026, 8, 15),
                "balance": Decimal("1700.00"),
                "days_overdue": 77,
            },
        ],
    }
