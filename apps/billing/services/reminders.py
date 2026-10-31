import logging
from datetime import date, timedelta
from typing import Optional
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceStatus, ReminderLog, ReminderStage

logger = logging.getLogger(__name__)


def send_due_reminders(today: Optional[date] = None) -> int:
    """
    Sends automated payment due reminders based on invoice due dates:
      - T-3: 3 days before due date
      - T+1: 1 day overdue
      - T+7: 7 days overdue
    Guaranteed idempotent via ReminderLog(invoice, stage) uniqueness constraint.
    Emails are sent after commit.
    Returns total reminders successfully scheduled.
    """
    if today is None:
        today = timezone.localdate()

    stages_config = [
        (ReminderStage.T_MINUS_3, today + timedelta(days=3)),
        (ReminderStage.T_PLUS_1, today - timedelta(days=1)),
        (ReminderStage.T_PLUS_7, today - timedelta(days=7)),
    ]

    sent_count = 0

    for stage, target_date in stages_config:
        # Candidate invoices: confirmed, unpaid or partially paid, with matching due_date
        invoices = (
            Invoice.objects.filter(
                status=InvoiceStatus.CONFIRMED,
                due_date=target_date,
            )
            .select_related("customer__user")
        )

        for inv in invoices:
            # Check if reminder already logged
            if ReminderLog.objects.filter(invoice=inv, stage=stage).exists():
                continue

            try:
                with transaction.atomic():
                    ReminderLog.objects.create(invoice=inv, stage=stage)

                    recipient = getattr(getattr(inv.customer, "user", None), "email", None)
                    if recipient:
                        stage_label = dict(ReminderStage.choices).get(stage, stage)
                        subject = f"Brightloop Payment Reminder ({stage_label}): Invoice #{inv.number or inv.id}"
                        body = (
                            f"Hello {inv.customer.name},\n\n"
                            f"This is a reminder regarding Invoice #{inv.number or inv.id}.\n"
                            f"Outstanding Balance: ₹ {inv.total - inv.amount_paid}\n"
                            f"Due Date: {inv.due_date}\n\n"
                            f"Please log in to your portal to complete payment: http://127.0.0.1:8000/portal/invoices/\n\n"
                            f"Thank you,\nBrightloop Billing Team"
                        )

                        def _send(email=recipient, subj=subject, msg=body):
                            try:
                                send_mail(
                                    subject=subj,
                                    message=msg,
                                    from_email=None,
                                    recipient_list=[email],
                                    fail_silently=True,
                                )
                            except Exception as exc:
                                logger.error(f"Failed to send reminder email to {email}: {exc}")

                        transaction.on_commit(_send)

                    sent_count += 1
            except IntegrityError:
                # Already sent by concurrent process
                continue

    return sent_count
