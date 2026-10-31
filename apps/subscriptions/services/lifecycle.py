from apps.subscriptions.models import Subscription, SubscriptionEvent, SubscriptionStatus


def activate(subscription: Subscription, actor=None) -> Subscription:
    """
    Activate a confirmed/draft subscription.
    Sets status=ACTIVE, billing_anchor=start_date, periods_billed=0, next_invoice_date=start_date.
    Logs a SubscriptionEvent.
    """
    from_status = subscription.status
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.billing_anchor = subscription.start_date
    subscription.periods_billed = 0
    subscription.next_invoice_date = subscription.start_date
    subscription.save(update_fields=[
        'status',
        'billing_anchor',
        'periods_billed',
        'next_invoice_date',
        'updated_at',
    ])

    SubscriptionEvent.objects.create(
        subscription=subscription,
        from_status=from_status,
        to_status=SubscriptionStatus.ACTIVE,
        action='activate',
        actor=actor,
        note='Subscription activated',
    )

    return subscription
