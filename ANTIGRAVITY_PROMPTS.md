# Antigravity prompts: first 90 minutes

Paste each prompt into the Antigravity agent panel in the order shown. Every prompt assumes `DESIGN.md` and `.agent/rules/subscription-system.md` are already in the repo.

## Roles

| Member | Role | Owns |
|---|---|---|
| **A** | Billing core | `apps/catalog` models, `apps/subscriptions` models, all of `apps/billing` (models + services) |
| **B** | Identity, catalog UI, portal | `config/`, `apps/accounts`, `apps/core`, `apps/portal`, views/forms for catalog and subscriptions |
| **C** | Experience and proof | `templates/`, `static/`, `apps/reports`, `seed_demo` |

Pick roles by strength. If backend is newest to you, take **C**: it is the most visible and agent-friendly, and you can still pair on one small service function.

## Before the clock starts (10 minutes, any one person)

1. Create a GitHub repo. Add `DESIGN.md`, `.agent/rules/subscription-system.md`, and `docs/ANTIGRAVITY_PROMPTS.md` to `main`. Invite the other two.
2. Everyone clones and opens the folder in Antigravity. If the Customizations panel asks how the rule should apply, choose **always on**.
3. Everyone runs the same Python version (3.12) and agrees on the chat channel for "I am changing X" announcements.

## Modes and habits

- **Planning mode** for billing, discounts, pricing, permissions, and models. **Fast mode** for CRUD screens, templates, and seed scripts.
- Review each agent's plan Artifact before it codes. Skim the diff before you commit.
- Small tasks beat big ones: one prompt, one commit.
- Branch per prompt: `git checkout -b feat/<short-name>`. Rebase often: `git pull --rebase origin main`. Merge to `main` when green. Never force-push `main`.
- Only the person named in a prompt runs `makemigrations`. If a migration conflict appears, stop and ask Member A.

## Timeline and sync points

| Time | A (billing core) | B (identity + UI) | C (experience + proof) |
|---|---|---|---|
| 0:00-0:15 | A0 read and plan | **B0 scaffold + accounts** | C0 base layout |
| **0:15** | **S0: B pushes scaffold, everyone pulls** | | |
| 0:15-0:45 | **A1 models** | B1 auth flows | C1 dashboard + print templates |
| **0:45** | **S1: A tags `models-frozen`, everyone pulls and migrates** | | |
| 0:45-1:10 | A2 pricing, tax, discounts | B2 RBAC + staff creation | C2 `seed_demo` |
| 1:10-1:30 | A3 billing run | B3 catalog CRUD UI | C3 reports service |
| **1:30** | **S2: merge everything to `main`, run `seed_demo`, `run_billing`, click through** | | |

---

## Prompt 0 (all members, minute 0)

```text
Mode: Fast. Do not write any code.
Read DESIGN.md and .agent/rules/subscription-system.md fully. Reply with:
1) a 10-bullet summary of the most important rules (billing idempotency, periods, discounts, state machines, RBAC, money, performance);
2) the folders I am allowed to edit if my role is <A | B | C>, based on DESIGN.md section 3;
3) any ambiguity or contradiction you notice in DESIGN.md (list only; do not fix).
```

---

## Member A: Billing core

### A0 (0:00-0:15): Review the model design
```text
Mode: Planning. Do not write code yet.
Read DESIGN.md sections 4, 5 and 6. I will implement the models for catalog, subscriptions and billing. Produce a plan Artifact that:
- lists every model with its fields, choices (TextChoices), UniqueConstraints, CheckConstraints and Indexes exactly as in section 4;
- flags any missing constraint or any rule in section 5 that cannot be enforced by the schema as written;
- proposes the exact method names for state transitions on Subscription and Invoice (confirm, activate, pause, resume, close, renew; confirm_invoice, cancel_invoice).
Do not add fields that are not in DESIGN.md. Keep it to one page.
```

### A1 (0:15-0:45): Models and migrations (start only after B0 is on main)
```text
Mode: Planning. Branch: feat/models-frozen.
Read DESIGN.md section 4 and .agent/rules. accounts.User, accounts.Customer and core.TimeStamped already exist from the scaffold.

Task: implement models and initial migrations for apps catalog, subscriptions and billing, exactly as specified in section 4.
Requirements:
- All models inherit core.TimeStamped. Money fields are DecimalField(max_digits=12, decimal_places=2).
- Use TextChoices for every status, interval, method, kind and scope.
- Implement every UniqueConstraint, CheckConstraint and Index listed (especially Invoice unique (subscription, period_start), Discount used_count <= usage_limit, Payment amount > 0, ProductVariant unique (product, attribute, value)).
- Add custom managers with for_user(user) on Subscription, Invoice, Payment and SubscriptionEvent: admin and staff see all; a customer sees only rows tied to their Customer profile; anonymous sees none.
- Register every model in Django admin with list_display, list_filter and search_fields so we can inspect data immediately.
- Add __str__ methods.
Do NOT write services, views, forms or templates. Do not touch accounts/ or config/.
Finish by running: python manage.py makemigrations, migrate, check, and makemigrations --check. Commit and push the branch, open a PR, and give me the summary. Then I will merge and tag `models-frozen`.
```

**At 0:45 (S1):** merge to `main`, run `git tag models-frozen && git push --tags`, and post "models frozen, pull and migrate" in chat.

### A2 (0:45-1:10): Pricing, tax, discount services
```text
Mode: Planning. Branch: feat/pricing-services. Models are frozen; do not change them.
Read DESIGN.md sections 5.1, 5.3 and 5.4.

Implement pure, well-tested services in apps/billing/services/:
- pricing.py: line_unit_price(product, variant, plan_or_none) -> Decimal (variant extra price added; the Odoo +560 example must be a test).
- tax.py: round_money(value) with ROUND_HALF_UP to 2 dp, and compute_tax(net, rate).
- discounts.py: find_best_discounts(lines, on_date) returning the line-level and subscription-level discount allocations according to the no-stacking rules; eligibility checks for dates, is_active, usage limit, min_amount, min_qty and scope; proportional allocation of a subscription-scope discount to lines with the rounding remainder on the last line; and redeem(discount, invoice) using an atomic conditional UPDATE (usage_limit IS NULL OR used_count < usage_limit), returning True/False, plus creating a DiscountRedemption.
- invoicing.py: build_invoice_draft(subscription, period_start) -> frozen dataclasses (InvoiceDraft, InvoiceLineDraft) with description, quantity, unit_price, discount_amount, discount reference, tax_rate, tax_amount, line_total, and the invoice totals subtotal, discount_total, tax_total, total. It must NOT write to the database.

Tests (Django TestCase, table-driven where possible) must cover: variant extra price, percent and fixed discounts, fixed discount capped at the line amount, min_amount and min_qty boundaries (just below, equal, above), start/end date edges, usage limit exhaustion and two parallel redemptions of the last use, product vs subscription scope, allocation remainder, tax rounding on a case like 33.33 at 18%, and totals reconciling (total == subtotal - discount_total + tax_total).
Run check, makemigrations --check and the tests. Commit, push, open a PR, and summarize.
```

### A3 (1:10-1:30): Billing run
```text
Mode: Planning. Branch: feat/billing-run. Read DESIGN.md sections 5.2, 5.5 and 6.

Implement apps/billing/services/billing_run.py::run_billing(as_of=None, dry_run=False, user=None) -> BillingRun exactly as in section 6:
- select active, non-paused subscriptions with next_invoice_date <= as_of in chunks of 200;
- each subscription in its own transaction with select_for_update(skip_locked=True), re-checking eligibility after the lock;
- catch-up loop while next_invoice_date <= as_of and next_invoice_date <= expiry_date, using billing_anchor and periods_billed with relativedelta (period_start(n) = anchor + n * interval_count * interval; never repeated addition);
- build the draft through build_invoice_draft, then create Invoice (draft) and InvoiceLines, redeem discounts, set invoice_date = period_start and due_date = invoice_date + payment_terms_days, advance periods_billed and next_invoice_date;
- IntegrityError on (subscription, period_start) counts as skipped and still advances the pointer;
- any other exception rolls back that subscription only and records a failed BillingRunItem with the error;
- dry_run writes nothing except returning the planned counts and totals;
- always record BillingRun and BillingRunItem rows (not for dry_run, return an in-memory result instead).
Add management command: python manage.py run_billing [--date YYYY-MM-DD] [--dry-run].
Also add subscriptions/services/lifecycle.py with activate(subscription) that sets billing_anchor=start_date, periods_billed=0, next_invoice_date=start_date and writes a SubscriptionEvent.

Tests: running twice creates zero new invoices; 3 missed monthly periods create exactly 3 invoices with correct period_start/period_end; a month-end anchor (31 Jan) gives correct 28/29 Feb and 31 Mar period starts; no invoice for a period starting after expiry_date; paused subscriptions are skipped; one failing subscription does not block the others (simulate with a mock); a discount with usage_limit=1 is redeemed only once across a double run; dry-run creates nothing.
Run check, makemigrations --check and all tests. Commit, push, PR, and summarize. List anything you did not finish.
```

---

## Member B: Identity, catalog UI, portal

### B0 (0:00-0:15): Scaffold and accounts (everyone waits for this, push to `main` directly this one time)
```text
Mode: Fast. Work on main (the only time we do this). Read DESIGN.md sections 2, 3 and 4 and .agent/rules.

Create the Django 5 project:
- project package `config`; apps under `apps/`: core, accounts, catalog, subscriptions, billing, reports, portal (empty apps with apps.py, models.py, services/__init__.py where relevant);
- settings: read env vars via python-dotenv; DATABASE_URL via dj-database-url (default SQLite); TIME_ZONE='Asia/Kolkata'; USE_TZ=True; templates dir at ./templates; static at ./static with whitenoise; EMAIL_BACKEND console by default and SMTP when EMAIL_HOST is set; AUTH_USER_MODEL='accounts.User'; LOGIN_URL, LOGIN_REDIRECT_URL;
- core/models.py: abstract TimeStamped (created_at auto_now_add, updated_at auto_now);
- accounts/models.py: custom User with email as USERNAME_FIELD, role TextChoices (admin/staff/customer, default customer), manager with create_user/create_superuser (superuser gets role=admin), UniqueConstraint(Lower('email')); Customer model exactly as in DESIGN.md section 4;
- minimal root urls with a placeholder home page;
- requirements.txt (Django, dj-database-url, psycopg[binary], python-dotenv, whitenoise, gunicorn, python-dateutil), .env.example, .gitignore, README with 3-command setup.
Do not create other models or views. Run makemigrations, migrate, check, and runserver smoke test. Commit and push to main with message "chore: scaffold project and accounts models". Tell me when it is pushed.
```

### B1 (0:15-0:45): Authentication flows
```text
Mode: Fast. Branch: feat/auth-flows. Read DESIGN.md sections 7 and 12. Touch only apps/accounts and templates/registration (the base layout templates/base.html is provided by Member C; extend it).

Implement:
- Signup page: email + password + confirm + name/company. Creates User(role=customer) and a linked Customer, logs them in, redirects to /portal/.
- Login with email, logout, and Django's built-in password reset flow (reset request, done, confirm, complete) with templates and the console email backend.
- accounts/validators.py: a custom password validator enforcing MORE than 8 characters (so at least 9), one uppercase, one lowercase, and one special character; register it in AUTH_PASSWORD_VALIDATORS with clear error messages.
- Case-insensitive email uniqueness with a friendly form error ("an account with this email already exists").
Tests: each weak-password case is rejected (8 chars, no upper, no lower, no special), a valid one is accepted, Alice@x.com and alice@x.com cannot both register, reset email is sent for a registered email and nothing leaks for an unknown email.
Run check and tests, commit, push, PR, and summarize.
```

### B2 (0:45-1:10): RBAC and staff creation (after `models-frozen`)
```text
Mode: Planning. Branch: feat/rbac. Read DESIGN.md section 7. Touch accounts/ and core/ only.

Implement:
- accounts/permissions.py: RoleRequiredMixin(allowed_roles=...), a role_required decorator, and helpers is_admin/is_staff_or_admin. Wrong role -> 403.
- core/querysets.py: a reusable ForUserQuerySetMixin documenting the for_user(user) convention (used by Member A's managers).
- Admin-only "Create staff" page at /staff/new/: form with name, email, temporary password (validated by the same validators), creates User(role=staff). Only admin can open it and post to it.
- Post-login redirect by role: admin and staff -> /reports/, customer -> /portal/.
- Navigation visibility helper (template context processor) exposing role flags, used by templates/base.html.
Tests: staff and customer get 403 on /staff/new/; admin can create staff; created staff can log in and cannot create staff; a customer requesting a staff-only URL gets 403; anonymous is redirected to login.
Run check and tests, commit, push, PR, summarize.
```

### B3 (1:10-1:30): Catalog CRUD UI
```text
Mode: Fast. Branch: feat/catalog-ui. Read DESIGN.md sections 4, 5.1 and 7. Models are frozen; do not change them. Touch apps/catalog (views, forms, urls, templates only) and the nav entries.

Build list/create/edit/delete (soft-delete via is_active where the model has it) screens for:
- Product with inline ProductVariant rows (attribute, value, extra_price);
- Plan (interval choices, min_qty, valid_from/valid_to, the four flags);
then, if time allows, Tax and Discount screens.
Rules: admin can write; staff can only view (read-only pages, no write buttons); customers get 403. Lists are paginated (25), searchable by name, and use the shared partials from Member C (templates/partials). Forms validate: prices >= 0, valid_to >= valid_from, min_qty >= 1, percent discount <= 100.
Tests for permissions (admin write OK, staff POST -> 403, customer 403) and for form validation edges.
Run check and tests, commit, push, PR, summarize.
```

---

## Member C: Experience and proof

### C0 (0:00-0:15): Base layout and shared partials
```text
Mode: Fast. Branch: feat/base-layout. Touch only templates/ and static/ (and apps/core/templatetags). Read DESIGN.md sections 2, 7 and 9. Until Member B pushes the scaffold, write files only; run them after pulling.

Create:
- templates/base.html: Bootstrap 5.3 + HTMX via CDN, HTMX sends the CSRF token header, a responsive navbar whose links depend on role (admin/staff/customer flags provided by a context processor named `role_flags`), messages area, blocks for title/content/extra_js.
- templates/partials/_pagination.html (works with Django's Paginator), _status_badge.html (colors for draft, quotation, confirmed, active, paused, closed, paid, overdue, cancelled), _form_field.html, _empty_state.html.
- apps/core/templatetags/ui.py with a `money` filter (₹ with thousands grouping and 2 decimals, Decimal-safe) and an `overdue_days` helper.
- A simple clean look (one accent color, readable tables). No JavaScript frameworks.
Commit, push, PR, and summarize. Remind the team the base layout is ready.
```

### C1 (0:15-0:45): Dashboard and print templates against a stub contract
```text
Mode: Fast. Branch: feat/dashboard-ui. Touch apps/reports and templates/reports plus apps/billing/templates/billing/invoice_print.html (templates only; no billing logic). Read DESIGN.md section 9.

Create apps/reports/services.py with get_summary(filters) that for now returns HARD-CODED data in exactly this shape (we will replace the body in C3 without changing the shape):
{ "active_subscriptions": int, "paused_subscriptions": int, "revenue_collected": Decimal, "billed": Decimal, "outstanding": Decimal, "overdue_count": int, "overdue_amount": Decimal, "mrr": Decimal, "arr": Decimal, "ageing": {"1-30": Decimal, "31-60": Decimal, "60+": Decimal}, "recent_payments": [ {"invoice_number": str, "customer": str, "amount": Decimal, "method": str, "paid_on": date} ], "overdue_invoices": [ {"number": str, "customer": str, "due_date": date, "balance": Decimal, "days_overdue": int} ] }

Build the /reports/ page (admin and staff only): a filter bar (date from/to, subscription status, customer text search) bound to GET params, summary cards, an ageing bar (Chart.js), tables for overdue invoices and recent payments with pagination partials. Also build an A4 print-friendly invoice template (invoice_print.html) that renders from an Invoice with lines, using @media print CSS and the money filter.
Tests: the page renders 200 for staff, 403 for customers, filter params are preserved in the form.
Run check and tests, commit, push, PR, summarize.
```

### C2 (0:45-1:10): `seed_demo` (after `models-frozen`)
```text
Mode: Fast. Branch: feat/seed-demo. Models are frozen; do not change them. Touch apps/reports/management/commands/seed_demo.py only. Read DESIGN.md section 11.

Implement: python manage.py seed_demo --customers 80 --subs 200 [--reset]
- Deterministic (random.seed(42)); --reset deletes only seeded data in dependency order; prints counts and elapsed time per step.
- Users (password Demo@12345): admin@brightloop.test (role=admin), staff@brightloop.test (role=staff), customer@brightloop.test (role=customer with a Customer profile and a few subscriptions), plus the bulk customers.
- Taxes (e.g. 18% default, 5%, 0%), 6 products with variants (include Brand: Odoo +560), 4 plans (monthly, yearly, weekly, one with auto_close=False), 3 discounts (one expiring within 7 days, one with usage_limit=5, one subscription-scope with min_qty), 2 quotation templates.
- Subscriptions with a realistic status mix (~60% active, 15% closed, 10% confirmed, 10% quotation, 5% draft), start dates spread across the last 12 months, correct billing_anchor/periods_billed/next_invoice_date for active ones, and about 10% of active subscriptions due today so a billing run has work.
- For active/closed subscriptions create historical invoices and payments using bulk_create in batches of 1000 (respect the unique (subscription, period_start) constraint; use billing.services.invoicing.build_invoice_draft if it exists on main, otherwise an inline simple calculation and leave a TODO to switch). Make a spread: mostly paid, some partial, some confirmed and overdue, a few draft.
- Support scaling: it must run with --subs 5000 in under ~2 minutes on SQLite and print the invoice count.
Add a test that seeds a tiny dataset (--subs 10) and asserts counts and that no invoice breaks its unique constraint. Run check and tests, commit, push, PR, summarize.
```

### C3 (1:10-1:30): Real reports and performance proof
```text
Mode: Planning. Branch: feat/reports-service. Touch apps/reports and apps/core/middleware.py only. Read DESIGN.md section 9.

Replace the body of reports.services.get_summary(filters) with real database aggregation, keeping the output shape unchanged:
- one aggregate query per metric group using conditional Sum/Count (no Python loops over rows): active/paused subscriptions, revenue collected (Payment.amount in the date range), billed (confirmed+paid invoice totals by invoice_date), outstanding (total - amount_paid over confirmed invoices), overdue count/amount and ageing buckets (1-30, 31-60, 60+ days) computed from due_date;
- MRR normalization from active non-paused subscription lines: daily x 30, weekly x 52/12, monthly x 1, yearly / 12, each divided by plan.interval_count; ARR = MRR x 12;
- filters: date range, status, customer search; paginated overdue invoices and recent payments using select_related.
Add core/middleware.py that logs each request's duration and query count and sets a Server-Timing header.
Tests: build a small dataset by hand and assert the exact summary numbers (including an overdue boundary at due_date == today and ageing bucket edges at 30/31 and 60/61 days), plus assertNumQueries (<= 12) for the dashboard. After seeding 5000 subs, print the dashboard response times; report them honestly even if above 2 seconds and propose the fix.
Run check and tests, commit, push, PR, summarize.
```

---

## S2 checkpoint (1:30): everyone together

```text
Mode: Fast. Pull main. Run in this order and report the result of each step with the exact errors if any:
python manage.py migrate
python manage.py seed_demo --customers 80 --subs 200 --reset
python manage.py run_billing --dry-run
python manage.py run_billing
python manage.py run_billing          # second run must create 0
python manage.py check && python manage.py makemigrations --check && python manage.py test
Then list the 5 biggest gaps between the current app and DESIGN.md section 12, ordered by demo risk.
```

## Next blocks (after 1:30)

- **A:** invoice actions (confirm, cancel, send, print), payment recording service and screen, `run_lifecycle`, billing preview page, coverage check.
- **B:** subscription CRUD with quotation templates and lifecycle buttons, portal screens, tax and discount screens.
- **C:** invoice list/detail screens, "Why this amount?" breakdown, portal next-invoice preview, ageing and reminders, README and demo script, performance run on 5k subscriptions.

## When an agent goes off track

```text
Stop. You changed files outside my folders / invented fields not in DESIGN.md. Revert those changes (git checkout -- <files>), re-read DESIGN.md section <N>, and redo only the requested task. List the exact files you will touch before editing.
```

```text
Before continuing, run python manage.py check, makemigrations --check, and the tests for the app you touched. Paste the real output. If anything fails, fix the cause; do not delete or skip tests.
```

```text
Explain in 5 lines what this function does with money (rounding, order of operations) and show a test that fails if the rounding changes.
```
