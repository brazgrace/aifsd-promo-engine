# ABOUTME: Promotion abstractions and implementations
# ABOUTME: Defines the Promotion protocol for implementing custom promotions

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

from promo_engine.domain import (
    AppliedDiscount,
    Cart,
    Money,
    Percentage,
    PricingContext,
    PromotionId,
    Sku,
)


@dataclass(frozen=True)
class PromotionConstraints:
    """
    Optional filters on pricing context.

    ``valid_from`` / ``valid_to`` bound ``PricingContext.now`` (inclusive ends if
    ``valid_to`` is the last instant inside the promo). Bounds and ``now`` must
    all be naive or all timezone-aware.

    Weekdays use ``datetime.weekday()`` convention: Monday = 0, Sunday = 6.
    Daypart uses ``context.now.time()`` in the same timezone awareness as ``now``.
    """

    valid_from: datetime | None = None
    valid_to: datetime | None = None
    allowed_weekdays: frozenset[int] | None = None
    daypart_start: time | None = None
    daypart_end: time | None = None
    required_customer_tags: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if (self.daypart_start is None) ^ (self.daypart_end is None):
            raise ValueError("daypart_start and daypart_end must both be set or both omitted")

    def allows(self, context: PricingContext) -> bool:
        now = context.now
        for bound in (b for b in (self.valid_from, self.valid_to) if b is not None):
            if (bound.tzinfo is None) != (now.tzinfo is None):
                raise ValueError(
                    "PromotionConstraints: valid_from/valid_to and PricingContext.now "
                    "must all be naive datetimes or all be timezone-aware."
                )
        if self.valid_from is not None and now < self.valid_from:
            return False
        if self.valid_to is not None and now > self.valid_to:
            return False
        if self.allowed_weekdays is not None and now.weekday() not in self.allowed_weekdays:
            return False
        if self.daypart_start is not None and self.daypart_end is not None:
            t = now.time()
            if self.daypart_start <= self.daypart_end:
                if not (self.daypart_start <= t <= self.daypart_end):
                    return False
            else:
                if not (t >= self.daypart_start or t <= self.daypart_end):
                    return False
        if self.required_customer_tags is not None and len(self.required_customer_tags) > 0:
            if not self.required_customer_tags <= context.customer_tags:
                return False
        return True


class Promotion(ABC):
    """Abstract base class for all promotions."""

    @property
    @abstractmethod
    def id(self) -> PromotionId:
        """Unique identifier for this promotion."""
        pass

    @property
    def priority(self) -> int:
        """Higher values run first. Ties broken by promotion id string order."""
        return 0

    @property
    def stackable(self) -> bool:
        """If False, this promotion is exclusive: no lower-priority promotions run after it."""
        return True

    @abstractmethod
    def is_applicable(self, cart: Cart, context: PricingContext) -> bool:
        """
        Determine if this promotion can be applied.

        Returns True if the promotion should be considered for this cart and context.
        """
        pass

    @abstractmethod
    def apply(self, cart: Cart, context: PricingContext) -> list[AppliedDiscount]:
        """
        Apply the promotion and return discount details.

        Should only be called if is_applicable returns True.
        Returns list of AppliedDiscount instances with full explainability.
        """
        pass


class PercentOffSkusPromotion(Promotion):
    """Percentage discount applied per eligible line; rounding per line (via Money)."""

    def __init__(
        self,
        promotion_id: PromotionId,
        percentage: Percentage,
        eligible_skus: frozenset[Sku],
        *,
        priority: int = 0,
        stackable: bool = True,
        constraints: PromotionConstraints | None = None,
        max_discount: Money | None = None,
    ) -> None:
        self._promotion_id = promotion_id
        self._percentage = percentage
        self._eligible_skus = eligible_skus
        self._priority = priority
        self._stackable = stackable
        self._constraints = constraints or PromotionConstraints()
        self._max_discount = max_discount

    @property
    def id(self) -> PromotionId:
        return self._promotion_id

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def stackable(self) -> bool:
        return self._stackable

    def is_applicable(self, cart: Cart, context: PricingContext) -> bool:
        if not self._constraints.allows(context):
            return False
        return any(
            line.quantity.value > 0 and line.product.sku in self._eligible_skus
            for line in cart.lines
        )

    def apply(self, cart: Cart, context: PricingContext) -> list[AppliedDiscount]:
        rate = self._percentage.as_decimal()
        allocations: dict[Sku, Money] = {}
        zero = Money(Decimal("0"))

        for line in cart.lines:
            if line.quantity.value <= 0 or line.product.sku not in self._eligible_skus:
                continue
            qty = Decimal(line.quantity.value)
            line_discount = line.unit_price * (qty * rate)
            sku = line.product.sku
            allocations[sku] = allocations.get(sku, zero) + line_discount

        if not allocations:
            return []

        raw_total = sum(allocations.values(), zero)
        if raw_total == zero:
            return []

        if self._max_discount is not None and raw_total > self._max_discount:
            scale = self._max_discount.amount / raw_total.amount
            allocations = {sku: amt * scale for sku, amt in allocations.items()}
            total = sum(allocations.values(), zero)
            drift = self._max_discount.amount - total.amount
            if drift != Decimal("0"):
                last_sku = max(allocations, key=lambda s: s.value)
                allocations[last_sku] = Money(allocations[last_sku].amount + drift)
            total = self._max_discount
        else:
            total = raw_total

        sku_part = ",".join(sorted(str(s) for s in allocations))
        details = (
            f"promotion_id={self._promotion_id} "
            f"percentage={self._percentage.value}% "
            f"skus={sku_part}"
        )

        return [
            AppliedDiscount(
                promotion_id=self._promotion_id,
                amount=total,
                target="line",
                details=details,
                allocations=dict(allocations),
            )
        ]


class FixedAmountOffPromotion(Promotion):
    """Fixed amount off the cart (nominal), optional minimum subtotal."""

    def __init__(
        self,
        promotion_id: PromotionId,
        amount_off: Money,
        *,
        minimum_subtotal: Money | None = None,
        priority: int = 0,
        stackable: bool = True,
        constraints: PromotionConstraints | None = None,
    ) -> None:
        self._promotion_id = promotion_id
        self._amount_off = amount_off
        self._minimum_subtotal = minimum_subtotal
        self._priority = priority
        self._stackable = stackable
        self._constraints = constraints or PromotionConstraints()

    @property
    def id(self) -> PromotionId:
        return self._promotion_id

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def stackable(self) -> bool:
        return self._stackable

    def is_applicable(self, cart: Cart, context: PricingContext) -> bool:
        if not self._constraints.allows(context):
            return False
        sub = cart.subtotal()
        if self._minimum_subtotal is not None and sub < self._minimum_subtotal:
            return False
        return sub > Money(Decimal("0"))

    def apply(self, cart: Cart, context: PricingContext) -> list[AppliedDiscount]:
        details = (
            f"promotion_id={self._promotion_id} "
            f"fixed_amount_off={self._amount_off.amount}"
        )
        return [
            AppliedDiscount(
                promotion_id=self._promotion_id,
                amount=self._amount_off,
                target="cart",
                details=details,
                allocations=None,
            )
        ]


class ThresholdPromotion(Promotion):
    """When cart subtotal reaches ``threshold``, apply fixed ``reward`` (spend X, save Y)."""

    def __init__(
        self,
        promotion_id: PromotionId,
        threshold: Money,
        reward: Money,
        *,
        priority: int = 0,
        stackable: bool = True,
        constraints: PromotionConstraints | None = None,
    ) -> None:
        self._promotion_id = promotion_id
        self._threshold = threshold
        self._reward = reward
        self._priority = priority
        self._stackable = stackable
        self._constraints = constraints or PromotionConstraints()

    @property
    def id(self) -> PromotionId:
        return self._promotion_id

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def stackable(self) -> bool:
        return self._stackable

    def is_applicable(self, cart: Cart, context: PricingContext) -> bool:
        if not self._constraints.allows(context):
            return False
        return cart.subtotal() >= self._threshold

    def apply(self, cart: Cart, context: PricingContext) -> list[AppliedDiscount]:
        details = (
            f"promotion_id={self._promotion_id} "
            f"threshold={self._threshold.amount} reward={self._reward.amount}"
        )
        return [
            AppliedDiscount(
                promotion_id=self._promotion_id,
                amount=self._reward,
                target="cart",
                details=details,
                allocations=None,
            )
        ]


class BuyXGetYPromotion(Promotion):
    """
    For ``target_sku``, every full bundle of ``buy_x + get_y`` units yields ``get_y``
    free units valued at the cheapest units in the pool (multi-line safe).
    """

    def __init__(
        self,
        promotion_id: PromotionId,
        target_sku: Sku,
        buy_x: int,
        get_y: int,
        *,
        priority: int = 0,
        stackable: bool = True,
        constraints: PromotionConstraints | None = None,
    ) -> None:
        if buy_x < 1 or get_y < 1:
            raise ValueError("buy_x and get_y must be >= 1")
        self._promotion_id = promotion_id
        self._target_sku = target_sku
        self._buy_x = buy_x
        self._get_y = get_y
        self._priority = priority
        self._stackable = stackable
        self._constraints = constraints or PromotionConstraints()

    @property
    def id(self) -> PromotionId:
        return self._promotion_id

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def stackable(self) -> bool:
        return self._stackable

    def _bundle_size(self) -> int:
        return self._buy_x + self._get_y

    def _total_qty(self, cart: Cart) -> int:
        return sum(
            line.quantity.value
            for line in cart.lines
            if line.product.sku == self._target_sku and line.quantity.value > 0
        )

    def _free_unit_count(self, cart: Cart) -> int:
        q = self._total_qty(cart)
        return (q // self._bundle_size()) * self._get_y

    def is_applicable(self, cart: Cart, context: PricingContext) -> bool:
        if not self._constraints.allows(context):
            return False
        return self._free_unit_count(cart) > 0

    def apply(self, cart: Cart, context: PricingContext) -> list[AppliedDiscount]:
        free_count = self._free_unit_count(cart)
        if free_count <= 0:
            return []

        unit_prices: list[Money] = []
        for line in cart.lines:
            if line.product.sku != self._target_sku or line.quantity.value <= 0:
                continue
            for _ in range(line.quantity.value):
                unit_prices.append(line.unit_price)

        unit_prices.sort(key=lambda m: m.amount)
        zero = Money(Decimal("0"))
        discount = sum(unit_prices[:free_count], zero)

        details = (
            f"promotion_id={self._promotion_id} "
            f"buy_x={self._buy_x} get_y={self._get_y} sku={self._target_sku}"
        )
        return [
            AppliedDiscount(
                promotion_id=self._promotion_id,
                amount=discount,
                target="line",
                details=details,
                allocations={self._target_sku: discount},
            )
        ]
