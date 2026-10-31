from decimal import Decimal, ROUND_HALF_UP

def round_money(val) -> Decimal:
    if val is None:
        return Decimal("0.00")
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def line_unit_price(product, variant=None, plan_or_none=None) -> Decimal:
    """
    Computes unit_price = base + variant.extra_price.
    base = plan.price for the plan's primary line and product.sales_price for add-on lines.
    """
    if plan_or_none:
        base = Decimal(str(plan_or_none.price))
    else:
        base = Decimal(str(product.sales_price))

    extra = Decimal("0.00")
    if variant and getattr(variant, "extra_price", None) is not None:
        extra = Decimal(str(variant.extra_price))

    return round_money(base + extra)
