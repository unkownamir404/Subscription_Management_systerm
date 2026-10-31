from decimal import Decimal, ROUND_HALF_UP

TWOPLACES = Decimal('0.01')


def round_money(value: Decimal | float | int | str) -> Decimal:
    """Round a monetary amount to 2 decimal places using ROUND_HALF_UP."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def compute_tax(net: Decimal | float | int | str, rate: Decimal | float | int | str) -> Decimal:
    """
    Compute tax on net amount given a percentage rate.
    Formula: round_half_up(net * rate / 100, 2)
    """
    if not isinstance(net, Decimal):
        net = Decimal(str(net))
    if not isinstance(rate, Decimal):
        rate = Decimal(str(rate))
    raw_tax = net * (rate / Decimal('100'))
    return round_money(raw_tax)
