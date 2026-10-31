from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


def add_interval(anchor: date, interval: str, count: int, n: int) -> date:
    """
    Computes anchor + (n * count * interval) using relativedelta.
    Calculated directly from the anchor (never cumulative repeated addition)
    so month-end dates do not drift.
    """
    total_units = n * max(1, count)
    if interval == "daily":
        delta = relativedelta(days=total_units)
    elif interval == "weekly":
        delta = relativedelta(weeks=total_units)
    elif interval == "monthly":
        delta = relativedelta(months=total_units)
    elif interval == "yearly":
        delta = relativedelta(years=total_units)
    else:
        delta = relativedelta(months=total_units)

    return anchor + delta


def period_start(anchor: date, interval: str, count: int, n: int) -> date:
    """
    Returns the period start date for period index n (0-indexed).
    period_start(anchor, interval, count, n) = add_interval(anchor, interval, count, n)
    """
    return add_interval(anchor, interval, count, n)


def period_end(anchor: date, interval: str, count: int, n: int) -> date:
    """
    Returns the period end date for period index n:
    period_end = period_start(..., n + 1) - 1 day
    """
    next_start = period_start(anchor, interval, count, n + 1)
    return next_start - timedelta(days=1)
