# ABOUTME: Core pricing engine that applies promotions to shopping carts
# ABOUTME: Orchestrates promotion evaluation and generates price summaries

from decimal import Decimal

from promo_engine.domain import (
    AppliedDiscount,
    Cart,
    Money,
    PriceSummary,
    PricingContext,
    PromotionId,
)
from promo_engine.promotions import Promotion


class PromotionEngine:
    """Main pricing engine that applies promotions to carts."""

    def __init__(self, promotions: list[Promotion]):
        """
        Initialize with a list of available promotions.

        Args:
            promotions: List of promotion instances to consider when pricing
        """
        self.promotions = promotions

    def price(self, cart: Cart, context: PricingContext) -> PriceSummary:
        """
        Calculate final price for a cart with applicable promotions.

        Algorithm:
        1. Calculate cart subtotal
        2. Sort promotions by priority (desc), then id
        3. Walk in order: record not applicable; apply applicable; stop after a non-stackable
        4. Sum nominal discount amounts (raw total)
        5. Set discount_total = min(subtotal, raw); total = subtotal - discount_total
        6. Return summary with applied discounts, not-applicable ids, and skipped ids

        Args:
            cart: Shopping cart to price
            context: Pricing context (time, channel, customer info)

        Returns:
            PriceSummary with subtotal, discounts, and total
        """
        subtotal = cart.subtotal()

        ordered = sorted(
            self.promotions,
            key=lambda p: (-p.priority, p.id.value),
        )

        all_discounts: list[AppliedDiscount] = []
        not_applicable: list[PromotionId] = []
        skipped_combination: list[PromotionId] = []
        stop_after_non_stackable = False

        for promotion in ordered:
            if stop_after_non_stackable:
                skipped_combination.append(promotion.id)
                continue
            if not promotion.is_applicable(cart, context):
                not_applicable.append(promotion.id)
                continue
            discounts = promotion.apply(cart, context)
            all_discounts.extend(discounts)
            if not promotion.stackable:
                stop_after_non_stackable = True

        raw_discount_total = Money(Decimal('0'))
        if all_discounts:
            raw_discount_total = sum(
                (d.amount for d in all_discounts),
                Money(Decimal('0'))
            )

        discount_total = (
            subtotal if raw_discount_total > subtotal else raw_discount_total
        )
        total = subtotal - discount_total

        return PriceSummary(
            subtotal=subtotal,
            discount_total=discount_total,
            total=total,
            applied_discounts=all_discounts,
            not_applicable_promotion_ids=tuple(not_applicable),
            skipped_due_to_combination_ids=tuple(skipped_combination),
        )
