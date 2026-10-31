from datetime import date
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.billing.services.billing_run import run_lifecycle


class Command(BaseCommand):
    help = "Runs subscription lifecycle maintenance (auto-close expired, expire quotations, send due reminders)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Target date in YYYY-MM-DD format (default: today)",
        )

    def handle(self, *args, **options):
        date_str = options.get("date")
        if date_str:
            try:
                as_of = date.fromisoformat(date_str)
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Invalid date format: {date_str}. Expected YYYY-MM-DD."))
                return
        else:
            as_of = timezone.localdate()

        self.stdout.write(self.style.MIGRATE_HEADING(f"Running Lifecycle Maintenance as of {as_of}..."))
        result = run_lifecycle(as_of)

        self.stdout.write(self.style.SUCCESS(
            f"Lifecycle run complete!\n"
            f"  - Auto-closed expired subscriptions: {result['auto_closed_subscriptions']}\n"
            f"  - Expired quotations identified:    {result['expired_quotations']}\n"
            f"  - Due reminders dispatched:          {result['reminders_sent']}\n"
            f"  - Renewal/expiry notices sent:       {result.get('subscription_reminders_sent', 0)}"
        ))
