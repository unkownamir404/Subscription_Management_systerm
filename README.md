# Brightloop - Subscription & Recurring Billing Management System

Brightloop is an end-to-end subscription business platform built with Django 5, Bootstrap 5, and HTMX. It manages the full customer subscription lifecycle: product catalog and variant pricing, quotation drafting, automated billing runs with tax and discount calculation, manual & self-service payment recording, multi-tenant customer self-service portal, and real-time revenue analytics.

---

## 1. Quickstart (3-Command Setup)

Get Brightloop running locally from a clean clone in three commands:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run migrations and populate deterministic demo dataset
python manage.py migrate && python manage.py seed_demo --customers 80 --subs 200 --reset

# 3. Start the development server
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in your browser.

> **Scale Testing (5,000 Subscriptions / ~60,000 Invoices):**
> ```bash
> python manage.py seed_demo --customers 400 --subs 5000 --reset
> ```

---

## 2. Demo User Credentials

The database seeder provisions three pre-configured accounts with distinct role-based permissions:

| Role | Email | Password | Access Scope |
|---|---|---|---|
| **Admin** | `admin@brightloop.test` | `Demo@12345` | Full administrative control: manage catalog (products, variants, plans, taxes, discounts), execute billing runs & previews, inspect coverage diagnostics, view financial reports, manage staff accounts. |
| **Staff** | `staff@brightloop.test` | `Demo@12345` | Operations management: create quotations, confirm & activate subscriptions, view catalog, inspect invoices & calculation panels, record customer payments, view revenue dashboards. Restricted from admin-only routes (HTTP 403). |
| **Customer** | `customer@brightloop.test` | `Demo@12345` | Self-service customer portal (`/portal/`): view personal subscriptions, preview upcoming invoices, self-service pause/renew, submit mock card payments. Restricted from other customers' data (HTTP 404) and internal staff routes. |

---

## 3. 5-Minute End-to-End Demo Walkthrough

Follow this scripted 5-minute walkthrough (from `DESIGN.md § 11`) to evaluate all core features:

### Step 1: Authentication & Password Validation
1. Navigate to `/signup/`.
2. Attempt to register with a weak password like `short` or `alllowercase123!`.
   - **Verification:** Form rejects the attempt, enforcing rules: minimum 9 characters, uppercase, lowercase, number, and special character.
3. Sign up with a valid compliant password (e.g. `Brightloop@2026!`). The user is created with `role=customer` and redirected to login.
4. Test password recovery: Click "Forgot Password" (`/password-reset/`) and submit `admin@brightloop.test`. Check terminal output where the reset link is output to console.

### Step 2: Product Catalog & Variant Pricing
1. Log in as **Admin** (`admin@brightloop.test` / `Demo@12345`).
2. Navigate to `/products/new/`. Create a product:
   - Name: `Enterprise ERP Suite`
   - Sales Price: `₹ 5,000`
   - Add Variant: Attribute `brand`, Extra Price `₹ 560` (e.g. "Odoo" variant per DESIGN.md § 5.1).
3. Navigate to `/plans/new/` and create a Monthly Recurring Plan at `₹ 1,200/month`.
4. Navigate to `/discounts/new/` and create a `10%` percentage discount with usage limit of 50.

### Step 3: Quotation & Subscription Lifecycle
1. Log in as **Staff** (`staff@brightloop.test` / `Demo@12345`).
2. Create or open a quotation for an existing customer. Add the `Enterprise ERP Suite` product with the `Odoo (+560)` variant and select the Monthly plan.
3. Advance the quotation through the lifecycle state machine:
   - `Draft` → `Quotation` → `Confirmed` → `Active`.
   - Notice the billing anchor date and first `next_invoice_date` are initialized automatically.

### Step 4: Billing Engine, Idempotency & Coverage Check
1. Log in as **Admin** and navigate to `/billing/run/`.
2. Select today's date (or future catch-up date) and click **"Preview Billing (Dry-Run)"**.
   - **Verification:** Shows projected invoice counts and skipped items. **Zero writes** are made to the database.
3. The **"Commit & Generate Invoices"** button dynamically appears. Click it to commit the billing run.
4. Navigate to `/invoices/` and click any generated invoice.
   - Expand the **"Why this amount?"** breakdown panel: verifies frozen unit price (`₹ 5,000` + `₹ 560` variant), line discounts, and line tax calculations.
5. Re-run billing for the exact same date.
   - **Verification:** Exactly **0 new invoices** are generated. Skipped counter increments, guaranteed by the `(subscription, period_start)` uniqueness constraint.
6. Open `/billing/coverage/`:
   - Both metrics display **0** in **Green** ("Active subscriptions with unbilled periods due = 0" and "Duplicate invoices = 0").

### Step 5: Payment Processing & Reconciliation
1. On the invoice detail page (`/invoices/<id>/`), inspect the invoice total and outstanding balance.
2. Record a partial payment (e.g. half of the total amount).
   - **Verification:** Invoice status remains `Confirmed` with a derived `Partially paid` badge, outstanding balance decreases.
3. Record the remaining balance.
   - **Verification:** Invoice automatically flips status to `Paid`. Attempting to record further payment displays validation error preventing overpayment.

### Step 6: Financial Reporting & Scale Performance
1. Navigate to `/reports/`.
2. Inspect the KPI cards: Active Subscriptions, Monthly Recurring Revenue (MRR), Annual Recurring Revenue (ARR), Total Billed, Revenue Collected, and Outstanding Balance.
3. Review the Overdue Invoices aging buckets (`1-30 days`, `31-60 days`, `60+ days`).
4. Test interactive filtering by Date Range, Customer, and Status.
5. Inspect response headers in Developer Tools: the `Server-Timing` header reveals server processing time (`app;dur=...`) and database queries (`db;dur=...`).

### Step 7: Customer Self-Service Portal & IDOR Protection
1. Log out and log in as **Customer** (`customer@brightloop.test` / `Demo@12345`).
2. Navigate to `/portal/`:
   - View only subscriptions and invoices belonging to this specific customer.
   - Preview the upcoming draft invoice calculation without writing to database.
   - Self-service: Click **"Pause"** or **"Renew"** on an eligible subscription.
   - Click **"Pay Now"** on an unpaid invoice to simulate mock card checkout.
3. Security check (IDOR protection): Attempt to manually browse to another customer's invoice `/portal/invoices/999/` or POST a payment.
   - **Verification:** System responds with HTTP 404 (not found) or 403 (forbidden).

---

## 4. Architecture Decisions & Known Limitations (DESIGN.md § 13)

| Architectural Decision | Chosen Implementation | Trade-off / Rationale |
|---|---|---|
| **Architecture** | Modular Monolith | Cohesive single Django project; eliminates distributed transaction overhead and network latency for an 8-hour hackathon build. |
| **Background Jobs** | CLI Command + Admin UI | No external dependency on Celery/Redis. The billing engine is strictly idempotent, enabling safe on-demand execution. |
| **Frontend Framework** | Server-Rendered Django + HTMX + Bootstrap 5 | Single codebase without SPA build pipelines; avoids API drift and maintains instant page renders with minimal JavaScript. |
| **Overdue Status** | Derived Dynamically | Overdue is derived at query time (`status=confirmed`, `due_date < today`, `amount_paid < total`) rather than a database enum, preventing stale state. |
| **Invoice Totals & Balance** | Denormalized on `Invoice` model | Subtotal, discounts, taxes, total, and `amount_paid` are denormalized on `Invoice` rows to keep list views sub-second without per-row aggregations. |
| **Pricing Snapshotting** | Immutable Invoicing Lines | Product prices and variant extras are frozen at the moment of invoice generation. Future catalog price updates never alter historical invoices. |
| **Discount Stacking** | Single Discount per Line | No multi-coupon stacking; prevents compounding calculation ambiguity and simplifies audit trails. |
| **Plan Changes** | Effective at Next Cycle | Plan tier adjustments take effect at the subsequent billing period; mid-cycle proration is omitted from current scope. |
| **Cancelled Invoices** | Keep Billing Period | Cancelled invoices retain their `period_start` to prevent automated billing from silently re-billing periods that were intentionally invalidated. |

### Scaling Roadmap (Future Enhancements):
- **Worker Queues:** Celery/Redis queue fan-out with randomized jitter for distributed billing execution.
- **Table Partitioning:** PostgreSQL declarative partitioning on `Invoice` by `period_start` and `Subscription` by billing anchor day.
- **Payment Gateway:** Real payment gateway integration (Stripe/Razorpay) with asynchronous webhooks and idempotency keys.
- **Proration & Metering:** Mid-cycle subscription changes, credit balances, trial periods, and usage-based metered billing lines.
- **Daily Aggregation Snapshots:** Pre-aggregated daily MRR/ARR tables for instantaneous multi-year cohort analysis.
- **Database Scaling:** PostgreSQL read replicas for reporting dashboards and portal reads.

---

## 5. Automated Test Checklist

Run the test suite across all subsystems:

```bash
python manage.py check && python manage.py makemigrations --check && python manage.py test apps.accounts apps.catalog apps.reports apps.portal apps.billing.tests.test_invoice_views apps.billing.tests.test_tax
```
