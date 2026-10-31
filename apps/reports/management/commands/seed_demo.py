"""
Brightloop Subscription Management System - Demo Seeding Command.
Populates deterministic demo data for customers, products, variants, plans,
discounts, templates, subscriptions, historical invoices, and payments.

Usage:
    python manage.py seed_demo --customers 80 --subs 200 [--reset]
    Scale benchmark: python manage.py seed_demo --customers 500 --subs 5000 [--reset]
"""

import sys
import time
import random
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Deterministically seeds realistic demo data for the Brightloop Subscription platform."

    def add_arguments(self, parser):
        parser.add_argument(
            "--customers",
            type=int,
            default=80,
            help="Number of customers to create (default: 80)",
        )
        parser.add_argument(
            "--subs",
            type=int,
            default=200,
            help="Number of subscriptions to create (default: 200)",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all previously seeded demo data before generating new data.",
        )

    def handle(self, *args, **options):
        customer_count = options["customers"]
        sub_count = options["subs"]
        reset = options["reset"]

        start_time = time.perf_counter()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"=== Brightloop Demo Seeding: {customer_count} Customers, {sub_count} Subscriptions ==="
        ))

        # Deterministic random seed
        random.seed(42)

        # Lazy model resolution to support modular development
        from django.apps import apps
        User = get_user_model()
        Customer = apps.get_model("accounts", "Customer")
        Tax = apps.get_model("catalog", "Tax")
        Product = apps.get_model("catalog", "Product")
        ProductVariant = apps.get_model("catalog", "ProductVariant")
        Plan = apps.get_model("catalog", "Plan")
        Discount = apps.get_model("catalog", "Discount")
        QuotationTemplate = apps.get_model("subscriptions", "QuotationTemplate")
        TemplateLine = apps.get_model("subscriptions", "TemplateLine")
        Subscription = apps.get_model("subscriptions", "Subscription")
        SubscriptionLine = apps.get_model("subscriptions", "SubscriptionLine")
        SubscriptionEvent = apps.get_model("subscriptions", "SubscriptionEvent")
        Invoice = apps.get_model("billing", "Invoice")
        InvoiceLine = apps.get_model("billing", "InvoiceLine")
        Payment = apps.get_model("billing", "Payment")
        DiscountRedemption = apps.get_model("billing", "DiscountRedemption")

        if reset:
            t0 = time.perf_counter()
            self.stdout.write("Resetting existing seeded demo data...")
            with transaction.atomic():
                Payment.objects.filter(invoice__customer__user__email__endswith="@brightloop.test").delete()
                InvoiceLine.objects.filter(invoice__customer__user__email__endswith="@brightloop.test").delete()
                Invoice.objects.filter(customer__user__email__endswith="@brightloop.test").delete()
                DiscountRedemption.objects.all().delete()
                SubscriptionEvent.objects.filter(subscription__customer__user__email__endswith="@brightloop.test").delete()
                SubscriptionLine.objects.filter(subscription__customer__user__email__endswith="@brightloop.test").delete()
                Subscription.objects.filter(customer__user__email__endswith="@brightloop.test").delete()
                TemplateLine.objects.all().delete()
                QuotationTemplate.objects.all().delete()
                Discount.objects.all().delete()
                ProductVariant.objects.all().delete()
                Product.objects.all().delete()
                Plan.objects.all().delete()
                Tax.objects.all().delete()
                Customer.objects.filter(user__email__endswith="@brightloop.test").delete()
                User.objects.filter(email__endswith="@brightloop.test").delete()
            self.stdout.write(self.style.SUCCESS(f"  Reset completed in {time.perf_counter() - t0:.2f}s"))

        today = timezone.localdate()

        # 1. Users & Customers
        t0 = time.perf_counter()
        self.stdout.write("1. Creating Users & Customers...")
        admin_user, _ = User.objects.get_or_create(
            email="admin@brightloop.test",
            defaults={"role": "admin", "is_staff": True, "is_superuser": True}
        )
        admin_user.set_password("Demo@12345")
        admin_user.save()

        staff_user, _ = User.objects.get_or_create(
            email="staff@brightloop.test",
            defaults={"role": "staff", "is_staff": True}
        )
        staff_user.set_password("Demo@12345")
        staff_user.save()

        primary_cust_user, _ = User.objects.get_or_create(
            email="customer@brightloop.test",
            defaults={"role": "customer"}
        )
        primary_cust_user.set_password("Demo@12345")
        primary_cust_user.save()

        Customer.objects.get_or_create(
            user=primary_cust_user,
            defaults={
                "name": "Acme Global Solutions",
                "company": "Acme Industries Ltd",
                "phone": "+91 98765 43210",
                "billing_address": "Tech Park, Whitefield, Bengaluru, KA 560066",
                "tax_id": "29ABCDE1234F1Z5",
            }
        )

        company_prefixes = [
            "Apex", "Zenith", "Nexus", "Quantum", "Hyperion", "Starlight", "BlueStar",
            "OmniCorp", "Vanguard", "CloudNine", "InfiniTech", "Pinnacle", "Titan", "Alpha"
        ]
        company_suffixes = ["Tech", "Software", "Logistics", "Digital", "Consulting", "Solutions", "Ventures"]

        bulk_users = []
        bulk_customers = []
        for i in range(1, customer_count):
            email = f"customer_{i}@brightloop.test"
            company = f"{random.choice(company_prefixes)} {random.choice(company_suffixes)} Pvt Ltd"
            user = User(email=email, role="customer")
            user.set_password("Demo@12345")
            bulk_users.append(user)

        created_users = User.objects.bulk_create(bulk_users, ignore_conflicts=True)
        # Fetch all customers user objects
        all_cust_users = list(User.objects.filter(email__endswith="@brightloop.test", role="customer"))
        for u in all_cust_users:
            if u.email == "customer@brightloop.test":
                continue
            name = u.email.split("@")[0].replace("_", " ").title()
            bulk_customers.append(Customer(
                user=u,
                name=f"{name} Manager",
                company=f"{name} Enterprises",
                phone=f"+91 9{random.randint(100000000, 999999999)}",
                billing_address=f"Building {random.randint(1, 99)}, Sector {random.randint(1, 40)}, Cyber Hub",
                tax_id=f"27{random.randint(100000000, 999999999)}Z1"
            ))
        Customer.objects.bulk_create(bulk_customers, ignore_conflicts=True)
        customers_pool = list(Customer.objects.filter(user__email__endswith="@brightloop.test"))
        self.stdout.write(self.style.SUCCESS(f"  Created {len(customers_pool)} customers in {time.perf_counter() - t0:.2f}s"))

        # 2. Taxes
        t0 = time.perf_counter()
        self.stdout.write("2. Creating Taxes...")
        tax_18, _ = Tax.objects.get_or_create(name="GST 18%", defaults={"rate": Decimal("18.00"), "is_default": True, "priority": 1})
        tax_5, _ = Tax.objects.get_or_create(name="GST 5%", defaults={"rate": Decimal("5.00"), "is_default": False, "priority": 2})
        tax_0, _ = Tax.objects.get_or_create(name="Exempt 0%", defaults={"rate": Decimal("0.00"), "is_default": False, "priority": 3})

        # 3. Products & Variants
        self.stdout.write("3. Creating Products & Variants...")
        p_erp, _ = Product.objects.get_or_create(
            name="Bright ERP Core",
            defaults={"product_type": "software", "sales_price": Decimal("5000.00"), "cost_price": Decimal("2000.00"), "tax": tax_18, "is_active": True}
        )
        ProductVariant.objects.get_or_create(product=p_erp, attribute="Brand", value="Odoo", defaults={"extra_price": Decimal("560.00")})
        ProductVariant.objects.get_or_create(product=p_erp, attribute="Brand", value="Brightloop", defaults={"extra_price": Decimal("0.00")})

        p_crm, _ = Product.objects.get_or_create(
            name="Cloud CRM Suite",
            defaults={"product_type": "software", "sales_price": Decimal("3000.00"), "cost_price": Decimal("1000.00"), "tax": tax_18, "is_active": True}
        )
        ProductVariant.objects.get_or_create(product=p_crm, attribute="Tier", value="Enterprise", defaults={"extra_price": Decimal("1500.00")})
        ProductVariant.objects.get_or_create(product=p_crm, attribute="Tier", value="Standard", defaults={"extra_price": Decimal("0.00")})

        p_sla, _ = Product.objects.get_or_create(
            name="Priority Support SLA",
            defaults={"product_type": "service", "sales_price": Decimal("1500.00"), "cost_price": Decimal("500.00"), "tax": tax_18, "is_active": True}
        )
        p_inv, _ = Product.objects.get_or_create(
            name="Automated Invoicing Engine",
            defaults={"product_type": "addon", "sales_price": Decimal("2000.00"), "cost_price": Decimal("400.00"), "tax": tax_18, "is_active": True}
        )
        p_api, _ = Product.objects.get_or_create(
            name="API Gateway & Webhooks",
            defaults={"product_type": "addon", "sales_price": Decimal("1200.00"), "cost_price": Decimal("300.00"), "tax": tax_18, "is_active": True}
        )
        p_consult, _ = Product.objects.get_or_create(
            name="Data Migration Consulting",
            defaults={"product_type": "service", "sales_price": Decimal("10000.00"), "cost_price": Decimal("4000.00"), "tax": tax_18, "is_active": True}
        )
        all_products = [p_erp, p_crm, p_sla, p_inv, p_api, p_consult]

        # 4. Plans
        self.stdout.write("4. Creating Plans...")
        plan_monthly, _ = Plan.objects.get_or_create(
            name="Monthly Growth",
            defaults={
                "price": Decimal("5000.00"),
                "interval": "monthly",
                "interval_count": 1,
                "min_qty": 1,
                "valid_from": today - timedelta(days=365),
                "auto_close": True,
                "allow_early_close": True,
                "allow_pause": True,
                "allow_renew": True,
            }
        )
        plan_yearly, _ = Plan.objects.get_or_create(
            name="Yearly Enterprise",
            defaults={
                "price": Decimal("50000.00"),
                "interval": "yearly",
                "interval_count": 1,
                "min_qty": 1,
                "valid_from": today - timedelta(days=365),
                "auto_close": True,
                "allow_early_close": True,
                "allow_pause": True,
                "allow_renew": True,
            }
        )
        plan_weekly, _ = Plan.objects.get_or_create(
            name="Weekly Sprint",
            defaults={
                "price": Decimal("1500.00"),
                "interval": "weekly",
                "interval_count": 1,
                "min_qty": 1,
                "valid_from": today - timedelta(days=365),
                "auto_close": True,
                "allow_early_close": True,
                "allow_pause": True,
                "allow_renew": True,
            }
        )
        plan_retainer, _ = Plan.objects.get_or_create(
            name="Perpetual Retainer",
            defaults={
                "price": Decimal("8000.00"),
                "interval": "monthly",
                "interval_count": 1,
                "min_qty": 1,
                "valid_from": today - timedelta(days=365),
                "auto_close": False,  # As required in prompt
                "allow_early_close": False,
                "allow_pause": True,
                "allow_renew": True,
            }
        )
        all_plans = [plan_monthly, plan_yearly, plan_weekly, plan_retainer]

        # 5. Discounts
        self.stdout.write("5. Creating Discounts...")
        # a) Expiring in 7 days
        d_expiring, _ = Discount.objects.get_or_create(
            name="Flash 10% Off",
            defaults={
                "kind": "percent",
                "value": Decimal("10.00"),
                "start_date": today - timedelta(days=23),
                "end_date": today + timedelta(days=7),
                "scope": "subscription",
                "is_active": True,
            }
        )
        # b) Usage limit = 5
        d_limited, _ = Discount.objects.get_or_create(
            name="Early Adopter ₹500",
            defaults={
                "kind": "fixed",
                "value": Decimal("500.00"),
                "usage_limit": 5,
                "used_count": 0,
                "start_date": today - timedelta(days=60),
                "end_date": today + timedelta(days=60),
                "scope": "products",
                "is_active": True,
            }
        )
        d_limited.products.add(p_erp, p_crm)
        # c) Subscription-scope with min_qty
        d_volume, _ = Discount.objects.get_or_create(
            name="Volume 15% Off",
            defaults={
                "kind": "percent",
                "value": Decimal("15.00"),
                "min_qty": 5,
                "start_date": today - timedelta(days=90),
                "end_date": today + timedelta(days=90),
                "scope": "subscription",
                "is_active": True,
            }
        )

        # 6. Quotation Templates
        self.stdout.write("6. Creating Quotation Templates...")
        t_starter, _ = QuotationTemplate.objects.get_or_create(
            name="SaaS Starter Template",
            defaults={"plan": plan_monthly, "validity_days": 30, "is_active": True}
        )
        TemplateLine.objects.get_or_create(template=t_starter, product=p_erp, defaults={"quantity": 1})
        TemplateLine.objects.get_or_create(template=t_starter, product=p_sla, defaults={"quantity": 1})

        t_enterprise, _ = QuotationTemplate.objects.get_or_create(
            name="Enterprise Suite Template",
            defaults={"plan": plan_yearly, "validity_days": 45, "is_active": True}
        )
        TemplateLine.objects.get_or_create(template=t_enterprise, product=p_crm, defaults={"quantity": 5})
        TemplateLine.objects.get_or_create(template=t_enterprise, product=p_api, defaults={"quantity": 1})

        # 7. Subscriptions Generation
        t0 = time.perf_counter()
        self.stdout.write("7. Building Subscriptions...")
        # Status distribution: 60% active, 15% closed, 10% confirmed, 10% quotation, 5% draft
        statuses = ["active"] * 60 + ["closed"] * 15 + ["confirmed"] * 10 + ["quotation"] * 10 + ["draft"] * 5

        subscriptions = []
        for i in range(1, sub_count + 1):
            status = statuses[i % len(statuses)]
            cust = customers_pool[i % len(customers_pool)]
            plan = all_plans[i % len(all_plans)]

            start_days_ago = random.randint(30, 360)
            start_date = today - timedelta(days=start_days_ago)

            # Terms & duration
            if plan.interval == "yearly":
                duration_years = 1
                expiry_date = start_date + relativedelta(years=duration_years)
            else:
                expiry_date = start_date + relativedelta(months=12)

            sub = Subscription(
                number=f"SUB-2026-{i:06d}",
                customer=cust,
                plan=plan,
                status=status,
                start_date=start_date,
                expiry_date=expiry_date,
                payment_terms_days=15,
                created_by=staff_user,
            )

            if status in ["active", "closed"]:
                sub.billing_anchor = start_date
                # Calculate billing periods elapsed
                if plan.interval == "monthly":
                    delta = relativedelta(months=1)
                elif plan.interval == "weekly":
                    delta = relativedelta(weeks=1)
                elif plan.interval == "yearly":
                    delta = relativedelta(years=1)
                else:
                    delta = relativedelta(days=1)

                # Count how many intervals fit between start_date and today
                periods = 0
                curr = start_date
                while curr <= today and curr <= expiry_date:
                    periods += 1
                    curr = start_date + (delta * periods)

                sub.periods_billed = max(1, periods - 1)
                sub.next_invoice_date = start_date + (delta * sub.periods_billed)

                # Make ~10% of active subscriptions due today
                if status == "active" and (i % 10 == 0):
                    sub.next_invoice_date = today

            subscriptions.append(sub)

        created_subs = Subscription.objects.bulk_create(subscriptions, batch_size=1000)
        all_subs = list(Subscription.objects.all())

        # Subscription Lines
        sub_lines = []
        for sub in all_subs:
            # Primary line
            sub_lines.append(SubscriptionLine(
                subscription=sub,
                product=p_erp,
                quantity=1,
                unit_price=sub.plan.price,
                tax_rate=Decimal("18.00"),
            ))
            # Optional add-on line
            if sub.id % 2 == 0:
                sub_lines.append(SubscriptionLine(
                    subscription=sub,
                    product=p_sla,
                    quantity=1,
                    unit_price=p_sla.sales_price,
                    tax_rate=Decimal("18.00"),
                ))
        SubscriptionLine.objects.bulk_create(sub_lines, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(f"  Created {len(all_subs)} subscriptions and {len(sub_lines)} lines in {time.perf_counter() - t0:.2f}s"))

        # 8. Historical Invoices & Payments Generation
        t0 = time.perf_counter()
        self.stdout.write("8. Generating Invoices and Payments...")
        invoices = []
        invoice_counter = 1

        # Track unique (subscription, period_start)
        seen_keys = set()

        for sub in all_subs:
            if sub.status not in ["active", "closed"]:
                continue

            interval_count = sub.plan.interval_count
            if sub.plan.interval == "monthly":
                delta = relativedelta(months=interval_count)
            elif sub.plan.interval == "weekly":
                delta = relativedelta(weeks=interval_count)
            elif sub.plan.interval == "yearly":
                delta = relativedelta(years=interval_count)
            else:
                delta = relativedelta(days=interval_count)

            # Generate historical invoices up to periods_billed
            for p in range(sub.periods_billed):
                p_start = sub.billing_anchor + (delta * p)
                key = (sub.id, p_start)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                p_end = p_start + delta - relativedelta(days=1)
                inv_date = p_start
                due_date = inv_date + timedelta(days=sub.payment_terms_days)

                # Status spread: mostly paid, some partial, some overdue, a few draft
                roll = random.random()
                if roll < 0.70:
                    inv_status = "paid"
                elif roll < 0.85:
                    inv_status = "confirmed"  # partial payment or pending
                elif roll < 0.95:
                    inv_status = "confirmed"  # overdue if due_date < today
                else:
                    inv_status = "draft"

                subtotal = sub.plan.price
                tax_total = (subtotal * Decimal("0.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                total = subtotal + tax_total

                if inv_status == "paid":
                    paid_amt = total
                elif inv_status == "confirmed" and roll < 0.85:
                    paid_amt = (total * Decimal("0.50")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                else:
                    paid_amt = Decimal("0.00")

                num = f"INV-2026-{invoice_counter:06d}" if inv_status != "draft" else None
                if num:
                    invoice_counter += 1

                invoices.append(Invoice(
                    number=num,
                    subscription=sub,
                    customer=sub.customer,
                    period_start=p_start,
                    period_end=p_end,
                    invoice_date=inv_date,
                    due_date=due_date,
                    status=inv_status,
                    subtotal=subtotal,
                    discount_total=Decimal("0.00"),
                    tax_total=tax_total,
                    total=total,
                    amount_paid=paid_amt,
                ))

        created_invoices = Invoice.objects.bulk_create(invoices, batch_size=1000)
        self.stdout.write(f"  Created {len(created_invoices)} invoices.")

        # Batch create InvoiceLines and Payments
        all_created_invoices = list(Invoice.objects.all())
        inv_lines = []
        payments = []
        payment_methods = ["bank_transfer", "card", "upi", "cheque", "cash"]

        for inv in all_created_invoices:
            # Simple line calculation
            # TODO: switch to billing.services.invoicing.build_invoice_draft when merged
            inv_lines.append(InvoiceLine(
                invoice=inv,
                description=f"{inv.subscription.plan.name} Recurring Service",
                product=p_erp,
                quantity=1,
                unit_price=inv.subtotal,
                discount_amount=Decimal("0.00"),
                tax_rate=Decimal("18.00"),
                tax_amount=inv.tax_total,
                line_total=inv.total,
            ))

            if inv.amount_paid > Decimal("0.00"):
                payments.append(Payment(
                    invoice=inv,
                    method=random.choice(payment_methods),
                    amount=inv.amount_paid,
                    paid_on=inv.invoice_date + timedelta(days=random.randint(1, 10)),
                    note="System-reconciled payment",
                    recorded_by=staff_user,
                ))

        InvoiceLine.objects.bulk_create(inv_lines, batch_size=1000)
        Payment.objects.bulk_create(payments, batch_size=1000)

        elapsed = time.perf_counter() - start_time
        self.stdout.write(self.style.SUCCESS(
            f"\nSeeding complete in {elapsed:.2f}s! Stats:\n"
            f"  - Users/Customers: {len(customers_pool)}\n"
            f"  - Subscriptions: {len(all_subs)}\n"
            f"  - Invoices: {len(all_created_invoices)}\n"
            f"  - Payments Recorded: {len(payments)}"
        ))


# =====================================================================
# Automated Unit Test for Seed Demo (Discovered by Django test runner)
# =====================================================================
from django.test import TestCase
from django.core.management import call_command


class SeedDemoTestCase(TestCase):
    def test_seed_demo_tiny_dataset_and_uniqueness(self):
        """
        Seeds a tiny dataset (--customers 5 --subs 10 --reset) and asserts:
        1. Correct model row counts
        2. Strict uniqueness of (subscription, period_start) on Invoice
        """
        from django.apps import apps
        Invoice = apps.get_model("billing", "Invoice")
        Subscription = apps.get_model("subscriptions", "Subscription")

        call_command("seed_demo", customers=5, subs=10, reset=True)

        subs_count = Subscription.objects.count()
        invoices = list(Invoice.objects.all())

        self.assertGreaterEqual(subs_count, 10)
        self.assertGreater(len(invoices), 0)

        # Check unique (subscription, period_start)
        seen = set()
        for inv in invoices:
            pair = (inv.subscription_id, inv.period_start)
            self.assertNotIn(pair, seen, f"Duplicate invoice period detected for {pair}!")
            seen.add(pair)
