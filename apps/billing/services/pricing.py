from decimal import Decimal
from typing import Any, Optional
from apps.billing.services.tax import round_money


def line_unit_price(
    product: Any,
    variant: Optional[Any] = None,
    plan_or_none: Optional[Any] = None,
) -> Decimal:
    """
    Calculate unit price for a subscription or quotation line.
    unit_price = base + variant.extra_price
    where base = plan.price for the primary line and product.sales_price for add-on lines.
    """
    if plan_or_none is not None:
        base = Decimal(str(plan_or_none.price))
    else:
        base = Decimal(str(product.sales_price))

    extra_price = Decimal('0.00')
    if variant is not None:
        variant_extra = getattr(variant, 'extra_price', None)
        if variant_extra is not None:
            extra_price = Decimal(str(variant_extra))

    return round_money(base + extra_price)
