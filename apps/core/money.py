from decimal import Decimal, ROUND_HALF_UP
from typing import Union

ZERO = Decimal("0.00")

def D(value: Union[int, str, float, Decimal]) -> Decimal:
    """
    Safely converts int, str, float, or Decimal to Decimal.
    For float values, converts through string first to avoid precision artifacts.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))

def q2(value: Union[int, str, float, Decimal]) -> Decimal:
    """
    Quantizes a monetary decimal value to 2 decimal places using standard ROUND_HALF_UP.
    """
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
