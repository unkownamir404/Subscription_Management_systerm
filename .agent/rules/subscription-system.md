# Rules: Brightloop Subscription Management System

## Source of truth
- Read `DESIGN.md` before planning any task. If these rules and `DESIGN.md` conflict, follow `DESIGN.md`. Never silently deviate: state the deviation and ask first.
- Do not invent models, fields, routes, or business rules that are not in `DESIGN.md`. If something is ambiguous, list the ambiguity and propose the smallest choice.

## Stack (do not change)
- Python 3.12, Django 5.x, PostgreSQL (SQLite for local dev), HTMX + Bootstrap 5, Chart.js. Server-rendered templates.
- Do NOT add Celery, Redis, Docker, React, DRF, or any new dependency without listing it and getting approval. Keep `requirements.txt` minimal.

## Ownership and boundaries
- Edit only the folders assigned in the task prompt. Never edit another owner's files (see DESIGN.md section 3).
- After the `models-frozen` tag, models and migrations change only when the task says so. Never edit or delete an existing migration; add a new one.
- Never commit secrets. Use environment variables and keep `.env.example` current.

## Architecture
- Business logic lives in `apps/<app>/services/`. Views, forms, admin, and templates stay thin and call services.
- Authorization is enforced in querysets (`Model.objects.for_user(user)`) and with `RoleRequiredMixin`. Hiding a button is never enough. Cross-customer access returns 404; wrong role returns 403.
- Never assign `status` fields directly. Use the transition methods/services, which validate state and write a `SubscriptionEvent`.

## Money and dates
- Money is `Decimal` only (never float), quantized to 2 decimals with `ROUND_HALF_UP`. Never compare or sum money as strings or floats.
- Snapshot prices and tax rates onto subscription lines and invoice lines. Never recompute or rewrite issued invoice data from the live catalog.
- Compute billing periods from `billing_anchor` with `dateutil.relativedelta`, never by repeated addition.
- Use timezone-aware datetimes and `django.utils.timezone`; dates for business periods are `date`.

## Correctness rules that must never break
- Billing is idempotent: unique `(subscription, period_start)` on invoices; catch `IntegrityError` and count it as skipped.
- Every subscription is billed in its own transaction with a row lock; one failure must not stop the run.
- Discount usage is redeemed with an atomic conditional update; never read-then-write the counter.
- Payments and invoice numbering run inside a transaction with a row lock on the invoice or counter.
- Overdue is derived at query time, never stored.

## Performance
- Every list is paginated (25 per page). Use `select_related` / `prefetch_related`; no queries inside template loops.
- Reports use database aggregation (`aggregate`, `annotate`, conditional `Sum`/`Count`), not Python loops over rows.
- Add an index only if it is listed in `DESIGN.md` or justified by a query you can show.

## Validation and security
- Validate on the server in forms and also at model/DB level (checks, constraints). CSRF on all POSTs. Escape output (no `|safe` on user data).
- Passwords: more than 8 characters with an uppercase letter, a lowercase letter, and a special character. Email is unique case-insensitively.

## Testing
- Every service function gets tests, including the failure and edge cases listed in DESIGN.md section 12. Use Django's test runner.
- Before saying a task is done, run: `python manage.py check`, `python manage.py makemigrations --check`, and `python manage.py test`. Report the results honestly, including failures.

## How to work
- Plan first for anything touching billing, discounts, pricing, or permissions: show a short plan, then implement in small steps. Simple CRUD can go straight to code.
- Keep changes small and scoped to the task. Do not refactor unrelated code or reformat files you were not asked to touch.
- Ask before running destructive commands (`rm -rf`, dropping databases, `git reset --hard`, `git push --force`, deleting migrations).
- Commit on a feature branch with a clear message (`feat(billing): ...`, `fix(accounts): ...`, `test(...)`, `docs(...)`). Never force-push `main`.
- At the end of every task, give a short summary: what changed, files touched, tests run and results, and anything left undone or assumed.
