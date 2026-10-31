from decimal import Decimal, ROUND_HALF_UP

def round_money(val) -> Decimal:
    if val is None:
        return Decimal("0.00")
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def compute_tax(net: Decimal, rate: Decimal) -> Decimal:
    """
    Computes tax on line discounted net: tax = round_half_up(net * rate / 100, 2)
    """
    if not rate or rate <= Decimal("0.00"):
        return Decimal("0.00")
    raw = (net * rate) / Decimal("100.00")
    return round_money(raw)
