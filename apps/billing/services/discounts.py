from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, List, Optional
from django.db.models import F, Q
from apps.billing.services.tax import round_money


@dataclass
class LineDiscountAllocation:
    line_index: int
    line_subtotal: Decimal
    product_discount: Optional[Any]
    product_discount_amount: Decimal
    subscription_discount: Optional[Any]
    subscription_discount_amount: Decimal
    total_discount_amount: Decimal


@dataclass
class BestDiscountsResult:
    line_allocations: List[LineDiscountAllocation]
    product_discounts_total: Decimal
    subscription_discount: Optional[Any]
    subscription_discount_total: Decimal
    total_discount: Decimal

    def __iter__(self):
        return iter(self.line_allocations)

    def __getitem__(self, index):
        return self.line_allocations[index]

    def __len__(self):
        return len(self.line_allocations)


def is_discount_date_and_status_eligible(discount: Any, on_date: date) -> bool:
    """Check basic status, date window, and usage limit of a discount."""
    if not getattr(discount, 'is_active', True):
        return False

    start_date = getattr(discount, 'start_date', None)
    end_date = getattr(discount, 'end_date', None)
    if start_date and on_date < start_date:
        return False
    if end_date and on_date > end_date:
        return False

    usage_limit = getattr(discount, 'usage_limit', None)
    used_count = getattr(discount, 'used_count', 0)
    if usage_limit is not None and used_count >= usage_limit:
        return False

    return True


def calculate_discount_saving(discount: Any, base_amount: Decimal) -> Decimal:
    """Calculate savings for a discount given an applicable base amount, capped at base_amount."""
    if base_amount <= Decimal('0.00'):
        return Decimal('0.00')

    kind = getattr(discount, 'kind', 'fixed')
    val = Decimal(str(getattr(discount, 'value', 0)))

    if kind == 'percent':
        saving = round_money(base_amount * (val / Decimal('100')))
    else:  # fixed
        saving = val

    return min(base_amount, max(Decimal('0.00'), saving))


def find_best_discounts(
    lines: Iterable[Any],
    on_date: date,
    available_discounts: Optional[Iterable[Any]] = None,
) -> BestDiscountsResult:
    """
    Find best line-level and subscription-level discounts under no-stacking rules.
    1. Filter eligible discounts by active status, date, and usage limits.
    2. Check min_amount and min_qty against applicable scopes.
    3. Select best product discount per line.
    4. Apply best subscription discount to remaining net balance.
    5. Allocate subscription discount proportionally with rounding remainder on last line.
    """
    lines_list = list(lines)
    if not lines_list:
        return BestDiscountsResult(
            line_allocations=[],
            product_discounts_total=Decimal('0.00'),
            subscription_discount=None,
            subscription_discount_total=Decimal('0.00'),
            total_discount=Decimal('0.00'),
        )

    # Load active discounts if not explicitly provided
    if available_discounts is None:
        from apps.catalog.models import Discount
        available_discounts = list(
            Discount.objects.filter(
                is_active=True,
                start_date__lte=on_date,
                end_date__gte=on_date,
            ).filter(
                Q(usage_limit__isnull=True) | Q(used_count__lt=F('usage_limit'))
            ).prefetch_related('products')
        )
    else:
        available_discounts = [
            d for d in available_discounts
            if is_discount_date_and_status_eligible(d, on_date)
        ]

    # Calculate line subtotals and totals
    line_subtotals: List[Decimal] = []
    line_quantities: List[int] = []
    total_qty = 0
    total_subtotal = Decimal('0.00')

    for line in lines_list:
        qty = int(getattr(line, 'quantity', 1))
        unit_price = Decimal(str(getattr(line, 'unit_price', '0.00')))
        sub = round_money(Decimal(qty) * unit_price)
        line_subtotals.append(sub)
        line_quantities.append(qty)
        total_qty += qty
        total_subtotal += sub

    # Separate discounts by scope
    product_discounts = [d for d in available_discounts if getattr(d, 'scope', 'subscription') == 'products']
    subscription_discounts = [d for d in available_discounts if getattr(d, 'scope', 'subscription') == 'subscription']

    # Step 1: For each line, evaluate eligible product-scope discounts
    # A product-scope discount is eligible if the total scoped subtotal >= min_amount and scoped qty >= min_qty
    line_best_product_discount: List[Optional[Any]] = [None] * len(lines_list)
    line_best_product_saving: List[Decimal] = [Decimal('0.00')] * len(lines_list)

    for disc in product_discounts:
        # Determine matching lines for this discount
        matching_indices = []
        if hasattr(disc, 'products'):
            if hasattr(disc.products, 'all'):
                disc_prod_ids = set(disc.products.values_list('id', flat=True))
            else:
                disc_prod_ids = {getattr(p, 'id', p) for p in disc.products}
        else:
            disc_prod_ids = set()

        for idx, line in enumerate(lines_list):
            prod = getattr(line, 'product', None)
            prod_id = getattr(prod, 'id', prod)
            if prod_id in disc_prod_ids or (prod and prod in disc_prod_ids):
                matching_indices.append(idx)

        if not matching_indices:
            continue

        scoped_subtotal = sum(line_subtotals[i] for i in matching_indices)
        scoped_qty = sum(line_quantities[i] for i in matching_indices)

        min_amt = Decimal(str(getattr(disc, 'min_amount', 0)))
        min_q = int(getattr(disc, 'min_qty', 0))

        if scoped_subtotal < min_amt or scoped_qty < min_q:
            continue

        # Evaluate saving per matching line
        for idx in matching_indices:
            line_sub = line_subtotals[idx]
            saving = calculate_discount_saving(disc, line_sub)
            if saving > line_best_product_saving[idx]:
                line_best_product_saving[idx] = saving
                line_best_product_discount[idx] = disc

    # Step 2: Remaining net after product discounts
    remaining_nets = [
        line_subtotals[i] - line_best_product_saving[i]
        for i in range(len(lines_list))
    ]
    total_remaining = sum(remaining_nets)

    # Step 3: Evaluate subscription-scope discounts on remaining net
    best_sub_discount = None
    best_sub_saving = Decimal('0.00')

    for disc in subscription_discounts:
        min_amt = Decimal(str(getattr(disc, 'min_amount', 0)))
        min_q = int(getattr(disc, 'min_qty', 0))

        if total_subtotal < min_amt or total_qty < min_q:
            continue

        saving = calculate_discount_saving(disc, total_remaining)
        if saving > best_sub_saving:
            best_sub_saving = saving
            best_sub_discount = disc

    # Step 4: Proportionally allocate subscription discount across lines with remainder on last line
    allocated_sub_discounts: List[Decimal] = [Decimal('0.00')] * len(lines_list)

    if best_sub_saving > Decimal('0.00') and total_remaining > Decimal('0.00'):
        running_allocated = Decimal('0.00')
        for i in range(len(lines_list) - 1):
            prop = remaining_nets[i] / total_remaining
            share = round_money(best_sub_saving * prop)
            # Cannot exceed remaining line amount
            share = min(share, remaining_nets[i])
            allocated_sub_discounts[i] = share
            running_allocated += share

        # Last line gets exact remainder of the subscription discount saving
        last_share = best_sub_saving - running_allocated
        allocated_sub_discounts[-1] = max(Decimal('0.00'), min(last_share, remaining_nets[-1]))

    # Step 5: Assemble allocations
    allocations: List[LineDiscountAllocation] = []
    total_product_discount = Decimal('0.00')
    total_sub_discount = Decimal('0.00')

    for i in range(len(lines_list)):
        p_disc = line_best_product_discount[i]
        p_amt = line_best_product_saving[i]
        s_amt = allocated_sub_discounts[i]
        tot_amt = p_amt + s_amt

        total_product_discount += p_amt
        total_sub_discount += s_amt

        allocations.append(
            LineDiscountAllocation(
                line_index=i,
                line_subtotal=line_subtotals[i],
                product_discount=p_disc,
                product_discount_amount=p_amt,
                subscription_discount=best_sub_discount if s_amt > 0 else None,
                subscription_discount_amount=s_amt,
                total_discount_amount=tot_amt,
            )
        )

    return BestDiscountsResult(
        line_allocations=allocations,
        product_discounts_total=total_product_discount,
        subscription_discount=best_sub_discount,
        subscription_discount_total=total_sub_discount,
        total_discount=total_product_discount + total_sub_discount,
    )


def redeem(discount: Any, invoice: Any) -> bool:
    """
    Atomically redeem a discount against an invoice.
    Uses: UPDATE discount SET used_count = used_count + 1 WHERE id = :id AND (usage_limit IS NULL OR used_count < usage_limit)
    Inserts a DiscountRedemption record when successful.
    Returns True if successfully redeemed, False if exhausted.
    """
    from apps.catalog.models import Discount
    from apps.billing.models import DiscountRedemption

    rows_updated = Discount.objects.filter(
        id=discount.id
    ).filter(
        Q(usage_limit__isnull=True) | Q(used_count__lt=F('usage_limit'))
    ).update(used_count=F('used_count') + 1)

    if rows_updated > 0:
        # Refresh in-memory used_count
        discount.refresh_from_db(fields=['used_count'])
        DiscountRedemption.objects.create(discount=discount, invoice=invoice)
        return True

    return False
