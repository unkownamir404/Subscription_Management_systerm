# Brightloop Subscription Management System — DESIGN

> Single source of truth for the team and for Antigravity agents. If code and this file disagree, this file wins until it is deliberately changed (tell the team first).

## 1. Goal and scope

Build one platform that runs a subscription business end to end: products and plans → quotations → subscriptions → automatic invoices → payments → revenue reporting, with three roles (admin, staff, customer portal).

**Assumptions:** currency is INR; payments are recorded manually or via a mock "Pay now" (no real gateway); 8-hour hackathon, 3 developers; seeded demo data is acceptable.

### MVP tiers

| Tier | Meaning | Items |
|---|---|---|
| **P0** | Must work in the demo | Auth + roles, catalog (products, variants, plans, taxes, discounts), quotation templates, subscription lifecycle, idempotent billing run, invoice lifecycle, payments, finance dashboard, performance proof |
| **P1** | Differentiators, build after P0 is green | Billing dry-run preview, "Why this amount?" price breakdown, billing coverage check, portal next-invoice preview + self-service (pause/close/renew), overdue ageing buckets + reminders, subscription status timeline |
| **P2** | Only if time remains | MRR/ARR with new/expansion/churned split, renewal radar, mock "Pay now", PDF/print polish, CSV export, GST-style tax split |

**Out of scope:** real payment gateway, proration, usage-based billing, trials, multi-currency, Celery/Redis, microservices.

## 2. Stack and conventions

- Python 3.12, Django 5.x, PostgreSQL (SQLite allowed for local dev only), HTMX + Bootstrap 5, Chart.js.
- Server-rendered templates; JSON endpoints only for charts.
- Config via environment variables (`.env`, never committed). `DATABASE_URL` via `dj-database-url`, default SQLite.
- Time zone `Asia/Kolkata`, `USE_TZ = True`.
- Tests use Django's test runner (`python manage.py test`).
- Email: console backend by default, SMTP when env vars are set.

## 3. Repo layout and ownership

```
.
├── DESIGN.md
├── .agent/rules/subscription-system.md
├── docs/ANTIGRAVITY_PROMPTS.md
├── manage.py
├── config/                  # settings, urls, wsgi
├── apps/
│   ├── core/                # TimeStamped base model, templatetags (money), middleware, helpers
│   ├── accounts/            # User, Customer, auth views, RBAC mixins             [Member B]
│   ├── catalog/             # Product, Variant, Plan, Tax, Discount + CRUD         [Member B UI, Member A models]
│   ├── subscriptions/       # Template, Subscription, Lines, Events, lifecycle     [Member B UI, Member A models]
│   ├── billing/             # Invoice, Payment, BillingRun + all services          [Member A]
│   ├── reports/             # dashboard + aggregate queries + seed_demo            [Member C]
│   └── portal/              # customer-facing views                                [Member B]
├── templates/               # base.html, partials                                  [Member C]
└── static/
```

Business logic lives in `apps/<app>/services/*.py`. Views, forms and admin stay thin and call services.

**Ownership rule:** edit only your own folders. Need a change elsewhere? Ask the owner or raise it in chat. After the `models-frozen` tag, **only Member A changes models/migrations** (announce first).

## 4. Domain model

All tables inherit `core.TimeStamped` (`created_at`, `updated_at`). Money fields are `DecimalField(max_digits=12, decimal_places=2)`.

### accounts
| Model | Fields | Constraints |
|---|---|---|
| `User` | `email`, `password`, `role` (`admin`/`staff`/`customer`, default `customer`), `is_active`, `is_staff` | `USERNAME_FIELD=email`; `UniqueConstraint(Lower("email"))` |
| `Customer` | `user` (1:1, null), `name`, `company`, `phone`, `billing_address`, `tax_id` | index on `name` |

### catalog
| Model | Fields | Constraints |
|---|---|---|
| `Tax` | `name`, `rate` (percent, 0-100), `is_default`, `priority` | check rate between 0 and 100 |
| `Product` | `name`, `product_type` (`service`/`software`/`addon`/`other`), `sales_price`, `cost_price`, `notes`, `tax` (FK, null), `is_active` | check prices ≥ 0 |
| `ProductVariant` | `product`, `attribute` (e.g. "Brand"), `value` (e.g. "Odoo"), `extra_price` (e.g. 560) | unique `(product, attribute, value)` |
| `Plan` | `name`, `price`, `interval` (`daily`/`weekly`/`monthly`/`yearly`), `interval_count` (default 1), `min_qty` (default 1), `valid_from`, `valid_to` (null), flags `auto_close`, `allow_early_close`, `allow_pause`, `allow_renew` | check `valid_to >= valid_from`; check `min_qty >= 1` |
| `Discount` | `name`, `kind` (`fixed`/`percent`), `value`, `min_amount` (default 0), `min_qty` (default 0), `start_date`, `end_date`, `usage_limit` (null = unlimited), `used_count`, `scope` (`products`/`subscription`), `products` (M2M, used when scope=products), `is_active` | check `used_count <= usage_limit` when limit set; check `end_date >= start_date`; percent ≤ 100 |

### subscriptions
| Model | Fields | Constraints |
|---|---|---|
| `QuotationTemplate` | `name`, `plan`, `validity_days`, `is_active` | |
| `TemplateLine` | `template`, `product`, `variant` (null), `quantity` | |
| `Subscription` | `number` (unique, `SUB-<year>-<id:06d>`), `customer`, `plan`, `status` (`draft`/`quotation`/`confirmed`/`active`/`closed`), `start_date`, `expiry_date`, `payment_terms_days` (default 15), `quote_valid_until` (null), `billing_anchor` (date, null), `periods_billed` (int, default 0), `next_invoice_date` (null), `paused_at` (null), `created_by` | indexes `(status, next_invoice_date)`, `customer`, `expiry_date` |
| `SubscriptionLine` | `subscription`, `product`, `variant` (null), `quantity`, `unit_price` (snapshot), `tax_rate` (snapshot) | check `quantity >= 1` |
| `SubscriptionEvent` | `subscription`, `from_status`, `to_status`, `action`, `actor`, `note` | index `(subscription, created_at)` |

### billing
| Model | Fields | Constraints |
|---|---|---|
| `Invoice` | `number` (null until confirmed, unique when set), `subscription`, `customer`, `period_start`, `period_end`, `invoice_date`, `due_date`, `status` (`draft`/`confirmed`/`paid`/`cancelled`), `subtotal`, `discount_total`, `tax_total`, `total`, `amount_paid` (default 0), `sent_at` (null) | **unique `(subscription, period_start)`**; indexes `(status, due_date)`, `customer`, `invoice_date`; check `amount_paid <= total` |
| `InvoiceLine` | `invoice`, `description`, `product` (null), `quantity`, `unit_price`, `discount_amount`, `tax_rate`, `tax_amount`, `line_total`, `discount` (FK, null) | frozen copy, never recomputed |
| `DiscountRedemption` | `discount`, `invoice` | unique `(discount, invoice)` |
| `Payment` | `invoice`, `method` (`bank_transfer`/`card`/`upi`/`cash`/`cheque`), `amount`, `paid_on`, `note`, `recorded_by` | check `amount > 0`; index `invoice` |
| `BillingRun` | `run_date`, `as_of`, `dry_run`, `started_by`, `created_count`, `skipped_count`, `failed_count`, `finished_at` | |
| `BillingRunItem` | `run`, `subscription`, `result` (`created`/`skipped`/`failed`), `invoice` (null), `error` | index `run` |
| `ReminderLog` | `invoice`, `stage` (`t_minus_3`/`t_plus_1`/`t_plus_7`) | unique `(invoice, stage)` |
| `InvoiceCounter` | `key` (e.g. `INV-2026`), `last_value` | locked with `select_for_update` |

## 5. Business rules

### 5.1 Pricing
- `unit_price = base + variant.extra_price`, where `base = plan.price` for the plan's primary line and `product.sales_price` for add-on lines. Example: the "Odoo" brand variant adds 560.
- Subscription lines **snapshot** `unit_price` and `tax_rate` at creation. Invoice lines are a frozen copy. Catalog changes never rewrite existing records.
- Assumption: `plan.min_qty` applies to each line's quantity on creation (validation error if below).
- A plan can be selected for **new** subscriptions only while `valid_from <= today <= valid_to`.

### 5.2 Periods (billed in advance)
- Anchor: on activation set `billing_anchor = start_date`, `periods_billed = 0`, `next_invoice_date = start_date`.
- `period_start(n) = billing_anchor + n × interval_count × interval` (computed from the anchor with `relativedelta`, **never** by repeated addition, so month-end dates do not drift).
- `period_end(n) = period_start(n+1) − 1 day`.
- An invoice for period *n* is due for generation when `today >= period_start(n)` **and** `period_start(n) <= expiry_date`.
- `invoice_date = period_start`, `due_date = invoice_date + payment_terms_days`.
- After generating period *n*: `periods_billed += 1`, `next_invoice_date = period_start(periods_billed)`.
- **Pause:** while `paused_at` is set, billing skips the subscription. On resume: `expiry_date += paused days`, `billing_anchor = resume date`, `periods_billed = 0`, `next_invoice_date = resume date`.
- **Expiry:** at `expiry_date`, if `plan.auto_close` the subscription becomes `closed` (lifecycle job). Otherwise it stays `active`, is flagged "Expired – needs renewal" in the UI, and appears on the renewal radar until staff renew or close it.
- **Renew** (only if `plan.allow_renew`): extends `expiry_date` by one plan term and logs an event.
- **Early close** (only if `plan.allow_early_close`): `closed` immediately; no further invoices.

### 5.3 Tax
- Tax rate comes from the line's product `Tax` (falling back to the default `Tax`, else 0).
- Tax is computed **per line on the discounted net**: `tax = round_half_up(line_net × rate / 100, 2)`.
- Invoice totals are sums of rounded line values: `total = subtotal − discount_total + tax_total`.

### 5.4 Discounts
- Eligible when: `is_active`, `start_date <= today <= end_date`, and `used_count < usage_limit` (or no limit).
- `min_amount`: scoped subtotal (matching lines for product scope, whole subtotal for subscription scope) must be ≥ it. `min_qty`: scoped total quantity must be ≥ it.
- **Product scope** applies to matching lines. **Subscription scope** applies to the subtotal and is allocated to lines proportionally, with the rounding remainder on the last line, so tax stays correct per line.
- **No stacking:** at most one product-scope discount per line (the one giving the largest saving) and at most one subscription-scope discount per invoice (largest saving). If both exist, the subscription-scope discount applies to the amount remaining after line discounts.
- Fixed discounts are capped at the amount they apply to. Percent is 0-100.
- **Redeem atomically** when the invoice is created: `UPDATE discount SET used_count = used_count + 1 WHERE id = :id AND (usage_limit IS NULL OR used_count < usage_limit)`. If zero rows updated, treat as exhausted and skip that discount. Insert a `DiscountRedemption` (counts once per invoice).

### 5.5 State machines
Transitions are model/service methods that validate the current state and write a `SubscriptionEvent`. Never assign `status` directly in views.

```
Subscription:  draft → quotation → confirmed → active → closed
               active ⇄ paused (flag `paused_at`, only if plan.allow_pause)
               quotation expires when quote_valid_until < today (cannot be confirmed)

Invoice:       draft → confirmed → paid
               draft | confirmed → cancelled   (only when amount_paid == 0; cancelled invoices keep their period)
```
- Invoice number `INV-<year>-<6 digits>` is assigned **on confirm** from `InvoiceCounter` under a row lock.
- An invoice moves to `paid` automatically when `amount_paid >= total`. Partial payments leave it `confirmed`; the UI shows a derived "Partially paid" badge.
- **Overdue is derived**, not stored: `status == confirmed and due_date < today`.

### 5.6 Payments
`record_payment(invoice, method, amount, paid_on, note, user)` runs in a transaction: lock the invoice row, require status `confirmed`, reject `amount <= 0` or amount greater than the balance, insert the payment, update `amount_paid`, set `paid` when settled.

## 6. Billing engine

`run_billing(as_of=today, dry_run=False, user=None) -> BillingRun`

1. Query: `status=active`, `paused_at IS NULL`, `next_invoice_date <= as_of`. Iterate in chunks of ~200.
2. For each subscription, in **its own transaction**, lock it (`select_for_update(skip_locked=True)`) and re-check eligibility. Then loop **while** `next_invoice_date <= as_of and next_invoice_date <= expiry_date` (catch-up for any missed periods):
   1. Build the draft with the pure function `build_invoice_draft(subscription, period_start)` (lines, discounts, tax, totals; no DB writes).
   2. If `dry_run`: record what would be created and continue.
   3. Insert `Invoice` (draft) + `InvoiceLine`s; redeem discounts; advance `periods_billed` / `next_invoice_date`.
3. `IntegrityError` on `(subscription, period_start)` → count as **skipped (already billed)**, still advance the pointer so the loop terminates.
4. Any other exception → roll back that subscription only, store `BillingRunItem(result=failed, error=...)`, continue.
5. Finish with counts on `BillingRun`. Re-running is always safe; failed items are retried on the next run.
6. Entry points: management command `python manage.py run_billing [--date YYYY-MM-DD] [--dry-run]` and an admin-only "Run billing" page with **preview (dry-run) then commit**.

**Lifecycle job** `run_lifecycle(as_of)`: auto-close expired subscriptions (`plan.auto_close`), mark stale quotations expired, send reminder emails (T-3, T+1, T+7 around due date; idempotent through `ReminderLog`). Emails are sent after commit and never roll back business data.

**Billing coverage check:** a report that counts Active, non-paused subscriptions with an unbilled period due on or before today (must be **0** after a run) and shows duplicate invoices per `(subscription, period_start)` (must be **0**, guaranteed by the constraint).

## 7. Access control

| Capability | Admin | Staff | Customer |
|---|---|---|---|
| Create staff / manage users | ✔ | ✖ | ✖ |
| Products, plans, taxes, discounts | write | read | ✖ |
| Customers | ✔ | ✔ | own profile |
| Quotation templates | ✔ | ✔ | ✖ |
| Subscriptions | ✔ | ✔ | own, read + allowed self-service |
| Invoices (confirm/cancel/send/print) | ✔ | ✔ | own, read/print |
| Payments | ✔ | ✔ | pay own via mock |
| Billing run, reports | ✔ | ✔ | ✖ |

Enforcement is **in the queryset**, not just the template: every queryset exposed to users goes through `Model.objects.for_user(user)`. Role checks use `RoleRequiredMixin`. Cross-customer access returns **404**; wrong role returns **403**.

## 8. Routes (server-rendered)

| Area | Routes |
|---|---|
| Auth | `/signup/`, `/login/`, `/logout/`, `/password-reset/…` |
| Users | `/staff/new/` (admin only) |
| Catalog | `/products/`, `/plans/`, `/taxes/`, `/discounts/` |
| Subscriptions | `/subscriptions/`, `/subscriptions/<id>/`, `POST …/confirm|activate|pause|resume|close|renew/`, `/templates/` |
| Billing | `/billing/run/` (preview then commit), `/billing/coverage/`, `/invoices/`, `/invoices/<id>/`, `POST …/confirm|cancel|send/`, `GET …/print/`, `POST …/payments/` |
| Reports | `/reports/`, `/api/reports/summary/?from=&to=&status=&customer=` |
| Portal | `/portal/`, `/portal/subscriptions/`, `/portal/invoices/`, `/portal/invoices/<id>/pay/` |

## 9. Reports and performance

**Definitions**
- *Active subscriptions*: `status=active and paused_at IS NULL` (paused shown separately).
- *Revenue collected*: sum of `Payment.amount` in the date range.
- *Billed*: sum of `Invoice.total` for confirmed and paid invoices by `invoice_date` in range.
- *Outstanding*: sum of `total − amount_paid` over confirmed invoices.
- *Overdue*: confirmed invoices with `due_date < today` (count, amount, ageing buckets 1-30 / 31-60 / 60+ days).
- *MRR* (approximate, pre-tax, pre-discount): active, non-paused lines normalized to monthly (`daily × 30`, `weekly × 52/12`, `monthly × 1`, `yearly ÷ 12`, divided by `interval_count`). `ARR = MRR × 12`.

**Targets:** every page responds in **under 2 seconds** with ~5,000 subscriptions and ~60,000 invoices.

**How:**
- The indexes in §4, and pagination (25 per page) on every list.
- `select_related` / `prefetch_related`; no per-row queries in templates.
- Denormalized `amount_paid` and invoice totals.
- Dashboard: one aggregate query per card (conditional aggregation). Optional 60-second cache keyed by filter hash.
- Request-duration logging middleware; `assertNumQueries` tests for list and dashboard views.

## 10. Reliability and error handling

- Per-subscription transactions in the billing run: one bad record never blocks the rest.
- Idempotency: unique `(subscription, period_start)`, unique `(discount, invoice)`, unique `(invoice, stage)` for reminders.
- Concurrency: row locks on subscription (billing), invoice (payment, numbering), atomic conditional update for discount usage.
- Validation at form **and** model/DB level (checks and constraints), never only in the browser.
- Emails after commit; failures logged, never fatal.

## 11. Seed data and demo script

`python manage.py seed_demo --customers 80 --subs 200 [--reset]` (scale test: `--subs 5000`). Deterministic random seed. Creates demo users (password `Demo@12345`): `admin@brightloop.test`, `staff@brightloop.test`, `customer@brightloop.test`, plus taxes, products with variants, plans (monthly, yearly, weekly), discounts (one expiring soon, one usage-limited), templates, subscriptions in all statuses, historical invoices and payments (some paid, partial, overdue) and about 10% of active subscriptions due today so billing has work.

## 12. Definition of done and test checklist

- [ ] Weak passwords rejected (≤ 8 chars, missing upper/lower/special); duplicate email (any case) rejected
- [ ] Password reset email delivered (console or SMTP)
- [ ] Only admin can create staff; staff and customers get 403 on admin-only pages
- [ ] Customer cannot open another customer's subscription or invoice (404)
- [ ] Variant extra price applied (Odoo +560)
- [ ] Subscription transitions follow the state machine; illegal jumps rejected
- [ ] Billing run twice creates no duplicates; 3 missed periods create 3 invoices; one failing subscription does not block others
- [ ] Discount appears automatically, respects dates, minimums, usage limit, and scope; stops after limit
- [ ] Tax computed from rules, rounding per line
- [ ] Payments update balance and flip invoice to Paid; overpayment rejected
- [ ] Dashboard numbers reconcile with raw data on the seeded dataset
- [ ] Every list and dashboard < 2 s on 5k subscriptions
- [ ] `python manage.py check`, `makemigrations --check`, and tests all pass on a clean clone
- [ ] README has 3-command setup, demo logins, and known limitations
