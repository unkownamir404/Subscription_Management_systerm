from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from apps.billing.services.billing_run import run_billing


class Command(BaseCommand):
    help = "Run idempotent subscription billing engine (preview or commit)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            dest='as_of_date',
            type=str,
            default=None,
            help='As-of billing date in YYYY-MM-DD format (defaults to today)',
        )
        parser.add_argument(
            '--dry-run',
            dest='dry_run',
            action='store_true',
            default=False,
            help='Simulate billing run without creating DB records',
        )

    def handle(self, *args, **options):
        as_of_str = options.get('as_of_date')
        dry_run = options.get('dry_run', False)

        as_of = None
        if as_of_str:
            try:
                as_of = datetime.strptime(as_of_str, '%Y-%m-%d').date()
            except ValueError:
                raise CommandError(f"Invalid date format: '{as_of_str}'. Expected YYYY-MM-DD.")

        mode_str = "PREVIEW (DRY-RUN)" if dry_run else "LIVE RUN"
        self.stdout.write(self.style.NOTICE(f"Starting billing run [{mode_str}] as of {as_of or 'today'}..."))

        result = run_billing(as_of=as_of, dry_run=dry_run)

        self.stdout.write(
            self.style.SUCCESS(
                f"Billing run completed: {result.created_count} created, "
                f"{result.skipped_count} skipped, {result.failed_count} failed."
            )
        )
