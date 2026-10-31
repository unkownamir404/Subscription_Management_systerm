"""
Performance Benchmarking Script for Brightloop Subscription Management System.
Measures Server-Timing metrics across all list views and reporting dashboards
on the scaled dataset (5,000 subscriptions, ~38,000 invoices).
"""

import os
import sys
import time
import re
import django

# Configure Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()

def parse_server_timing(header_val):
    """
    Parses 'app;dur=123.45, db;dur=67.89;desc="12 queries"' into a dict.
    """
    if not header_val:
        return {"app_dur": 0.0, "db_dur": 0.0, "queries": 0}

    app_dur = 0.0
    db_dur = 0.0
    queries = 0

    m_app = re.search(r'app;dur=([0-9.]+)', header_val)
    if m_app:
        app_dur = float(m_app.group(1))

    m_db = re.search(r'db;dur=([0-9.]+)', header_val)
    if m_db:
        db_dur = float(m_db.group(1))

    m_q = re.search(r'desc="([0-9]+) queries"', header_val)
    if m_q:
        queries = int(m_q.group(1))

    return {"app_dur": app_dur, "db_dur": db_dur, "queries": queries}


def run_benchmark():
    admin_user = User.objects.filter(email="admin@brightloop.test").first()
    customer_user = User.objects.filter(email="customer@brightloop.test").first()

    if not admin_user or not customer_user:
        print("ERROR: admin or customer demo user not found in database.")
        sys.exit(1)

    admin_client = Client()
    admin_client.force_login(admin_user)

    customer_client = Client()
    customer_client.force_login(customer_user)

    routes = [
        # (name, path, client_type, role)
        ("Reports Dashboard", "/reports/", admin_client, "Admin/Staff"),
        ("Reports Summary API", "/reports/api/summary/", admin_client, "Admin/Staff"),
        ("Invoice List", "/invoices/", admin_client, "Admin/Staff"),
        ("Invoice Overdue Filter", "/invoices/?status=overdue", admin_client, "Admin/Staff"),
        ("Product List", "/products/", admin_client, "Admin/Staff"),
        ("Plan List", "/plans/", admin_client, "Admin/Staff"),
        ("Tax List", "/taxes/", admin_client, "Admin/Staff"),
        ("Discount List", "/discounts/", admin_client, "Admin/Staff"),
        ("Billing Coverage Check", "/billing/coverage/", admin_client, "Admin"),
        ("Billing Run UI", "/billing/run/", admin_client, "Admin"),
        ("Customer Portal Dashboard", "/portal/", customer_client, "Customer"),
        ("Customer Portal Subscriptions", "/portal/subscriptions/", customer_client, "Customer"),
        ("Customer Portal Invoices", "/portal/invoices/", customer_client, "Customer"),
    ]

    print("\n" + "=" * 90)
    print("BRIGHTLOOP SCALE PERFORMANCE BENCHMARK (5,000 SUBSCRIPTIONS / ~38,000 INVOICES)")
    print("=" * 90)

    results = []

    for name, path, client, role in routes:
        # Run warm-up and measurement
        t0 = time.perf_counter()
        resp = client.get(path)
        wall_time_ms = (time.perf_counter() - t0) * 1000.0

        timing_header = resp.headers.get("Server-Timing", "")
        parsed = parse_server_timing(timing_header)

        # Do a second run to measure warm cache / steady state
        t1 = time.perf_counter()
        resp_warm = client.get(path)
        warm_wall_ms = (time.perf_counter() - t1) * 1000.0
        warm_parsed = parse_server_timing(resp_warm.headers.get("Server-Timing", ""))

        status = resp.status_code
        app_ms = warm_parsed["app_dur"] or warm_wall_ms
        db_ms = warm_parsed["db_dur"]
        queries = warm_parsed["queries"]
        flag = "FAIL (>2s)" if app_ms > 2000.0 else "PASS (<2s)"

        results.append({
            "name": name,
            "path": path,
            "role": role,
            "status": status,
            "cold_ms": wall_time_ms,
            "warm_ms": app_ms,
            "db_ms": db_ms,
            "queries": queries,
            "flag": flag,
        })

    # Print Markdown Table
    print(f"\n| {'Page / Endpoint':<28} | {'Role':<12} | {'HTTP':<4} | {'Queries':<7} | {'DB Time (ms)':<12} | {'App Time (ms)':<13} | {'Status':<10} |")
    print(f"|{'-'*30}|{'-'*14}|{'-'*6}|{'-'*9}|{'-'*14}|{'-'*15}|{'-'*12}|")

    for r in results:
        print(f"| {r['name']:<28} | {r['role']:<12} | {r['status']:<4} | {r['queries']:<7} | {r['db_ms']:<12.2f} | {r['warm_ms']:<13.2f} | {r['flag']:<10} |")

    print("\n" + "=" * 90)
    flagged = [r for r in results if r["flag"] == "FAIL (>2s)"]
    if flagged:
        print(f"WARNING: {len(flagged)} endpoint(s) exceeded the 2.0s limit!")
        for f in flagged:
            print(f"  - {f['name']} ({f['path']}): {f['warm_ms']:.2f} ms")
    else:
        print("SUCCESS: ALL list views and dashboards responded in UNDER 2 SECONDS (100% PASS)!")
    print("=" * 90 + "\n")

if __name__ == "__main__":
    run_benchmark()
