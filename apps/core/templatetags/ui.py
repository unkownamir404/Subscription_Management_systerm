"""
UI templatetags for Brightloop Subscription Management System.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, datetime
from django import template
from django.utils import timezone

register = template.Library()


@register.filter(name="money")
def money(value):
    """
    Format a number or Decimal as INR currency (₹) with 2 decimals and Indian grouping.
    Decimal-safe. Handles None, negative values, and invalid numbers cleanly.
    Example: 1234567.89 -> '₹12,34,567.89'
             -500.5 -> '-₹500.50'
    """
    if value is None or value == "":
        return "₹0.00"

    try:
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "₹0.00"

    is_negative = value < 0
    abs_value = abs(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    integer_part, decimal_part = f"{abs_value:.2f}".split(".")

    # Indian numbering format grouping: last 3 digits, then groups of 2 digits
    if len(integer_part) > 3:
        last_three = integer_part[-3:]
        remaining = integer_part[:-3]
        groups = []
        while remaining:
            groups.append(remaining[-2:])
            remaining = remaining[:-2]
        groups.reverse()
        formatted_int = ",".join(groups) + "," + last_three
    else:
        formatted_int = integer_part

    prefix = "-₹" if is_negative else "₹"
    return f"{prefix}{formatted_int}.{decimal_part}"


@register.filter(name="get_item")
def get_item(dictionary, key):
    """
    Look up dictionary key that may contain hyphens or special characters.
    Usage: {{ summary.ageing|get_item:"1-30" }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(str(key), "")
    return ""


@register.filter(name="overdue_days")
def overdue_days(due_date):
    """
    Returns number of days overdue relative to current local date.
    Returns 0 if due_date is in the future, today, or invalid.
    """
    if not due_date:
        return 0

    if isinstance(due_date, datetime):
        due_date = due_date.date()
    elif not isinstance(due_date, date):
        try:
            due_date = datetime.strptime(str(due_date), "%Y-%m-%d").date()
        except ValueError:
            return 0

    today = timezone.localdate()
    delta = (today - due_date).days
    return max(0, delta)


@register.simple_tag
def status_class(status):
    """
    Returns the appropriate Bootstrap badge CSS class for a given status.
    """
    key = str(status).strip().lower() if status else ""
    mapping = {
        "draft": "badge bg-secondary",
        "quotation": "badge bg-info text-dark",
        "confirmed": "badge bg-primary",
        "active": "badge bg-success",
        "paused": "badge bg-warning text-dark",
        "closed": "badge bg-dark",
        "paid": "badge bg-success",
        "overdue": "badge bg-danger",
        "cancelled": "badge bg-danger bg-opacity-75",
        "failed": "badge bg-danger",
        "skipped": "badge bg-secondary",
        "created": "badge bg-success",
    }
    return mapping.get(key, "badge bg-light text-dark border")
