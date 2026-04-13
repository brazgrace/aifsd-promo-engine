# ABOUTME: Promotion abstractions and implementations
# ABOUTME: Defines the Promotion protocol for implementing custom promotions

from __future__ import annotations

from abc import ABC, abstractmethod
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


# TODO: Add time-based applicability (valid_from, valid_until)
# TODO: Add day-of-week and time-of-day restrictions
# TODO: Add customer segment targeting using context.customer_tags
# TODO: Add maximum discount caps
# TODO: Consider BuyXGetYPromotion for quantity-based discounts
# TODO: Consider FixedAmountOffPromotion
# TODO: Consider ThresholdPromotion (spend $X, save $Y)


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
    ) -> None:
        self._promotion_id = promotion_id
        self._percentage = percentage
        self._eligible_skus = eligible_skus
        self._priority = priority
        self._stackable = stackable

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

        total = sum(allocations.values(), zero)
        if total == zero:
            return []

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
