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
    StackingPolicy,
)
from promo_engine.promotions import Promotion


class PromotionEngine:
    """Main pricing engine that applies promotions to carts."""

    def __init__(
        self,
        promotions: list[Promotion],
        stacking_policy: StackingPolicy = StackingPolicy.STACK,
    ):
        """
        Initialize with a list of available promotions.

        Args:
            promotions: List of promotion instances to consider when pricing
            stacking_policy: How to combine multiple applicable promotions
        """
        self.promotions = promotions
        self.stacking_policy = stacking_policy

    @staticmethod
    def _ordered(promotions: list[Promotion]) -> list[Promotion]:
        return sorted(promotions, key=lambda p: (-p.priority, p.id.value))

    @staticmethod
    def _sum_discount_amounts(discounts: list[AppliedDiscount]) -> Money:
        if not discounts:
            return Money(Decimal("0"))
        return sum((d.amount for d in discounts), Money(Decimal("0")))

    def _walk_stack_mode(
        self, cart: Cart, context: PricingContext
    ) -> tuple[list[AppliedDiscount], list[PromotionId], list[PromotionId]]:
        """Priority walk with per-promotion non-stackable early stop (legacy STACK)."""
        ordered = self._ordered(self.promotions)
        all_discounts: list[AppliedDiscount] = []
        not_applicable: list[PromotionId] = []
        skipped: list[PromotionId] = []
        stop_after_non_stackable = False

        for promotion in ordered:
            if stop_after_non_stackable:
                if promotion.is_applicable(cart, context):
                    skipped.append(promotion.id)
                continue
            if not promotion.is_applicable(cart, context):
                not_applicable.append(promotion.id)
                continue
            discounts = promotion.apply(cart, context)
            all_discounts.extend(discounts)
            if not promotion.stackable:
                stop_after_non_stackable = True

        return all_discounts, not_applicable, skipped

    def _collect_all_applicable(
        self, cart: Cart, context: PricingContext
    ) -> tuple[list[tuple[Promotion, list[AppliedDiscount]]], list[PromotionId]]:
        """Every applicable promotion is evaluated (no stackable early stop)."""
        ordered = self._ordered(self.promotions)
        candidates: list[tuple[Promotion, list[AppliedDiscount]]] = []
        not_applicable: list[PromotionId] = []

        for promotion in ordered:
            if not promotion.is_applicable(cart, context):
                not_applicable.append(promotion.id)
                continue
            candidates.append((promotion, promotion.apply(cart, context)))

        return candidates, not_applicable

    @staticmethod
    def _resolve_exclusive_best(
        candidates: list[tuple[Promotion, list[AppliedDiscount]]],
    ) -> tuple[list[AppliedDiscount], list[PromotionId]]:
        if not candidates:
            return [], []

        def better(
            j: int,
            total_j: Money,
            p_j: Promotion,
            best_i: int,
            total_b: Money,
            p_b: Promotion,
        ) -> bool:
            if total_j > total_b:
                return True
            if total_j < total_b:
                return False
            if p_j.priority > p_b.priority:
                return True
            if p_j.priority < p_b.priority:
                return False
            if p_j.id.value < p_b.id.value:
                return True
            if p_j.id.value > p_b.id.value:
                return False
            return j < best_i

        best_i = 0
        best_total = PromotionEngine._sum_discount_amounts(candidates[0][1])
        best_promo, best_disc = candidates[0]
        for j in range(1, len(candidates)):
            promo, discs = candidates[j]
            t = PromotionEngine._sum_discount_amounts(discs)
            if better(j, t, promo, best_i, best_total, best_promo):
                best_i = j
                best_total = t
                best_promo, best_disc = promo, discs

        skipped = [p.id for k, (p, _) in enumerate(candidates) if k != best_i]
        return list(best_disc), skipped

    @staticmethod
    def _resolve_exclusive_priority(
        candidates: list[tuple[Promotion, list[AppliedDiscount]]],
    ) -> tuple[list[AppliedDiscount], list[PromotionId]]:
        if not candidates:
            return [], []

        for idx, (promo, discs) in enumerate(candidates):
            if discs:
                skipped = [p.id for p, _ in candidates[idx + 1 :]]
                return list(discs), skipped

        skipped = [p.id for p, _ in candidates]
        return [], skipped

    def price(self, cart: Cart, context: PricingContext) -> PriceSummary:
        """
        Calculate final price for a cart with applicable promotions.

        Algorithm:
        1. Calculate cart subtotal
        2. Sort promotions by priority (desc), then id
        3. Resolve discounts per ``stacking_policy`` (STACK vs exclusive modes)
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

        if self.stacking_policy == StackingPolicy.STACK:
            all_discounts, not_applicable, skipped_combination = self._walk_stack_mode(
                cart, context
            )
        else:
            candidates, not_applicable = self._collect_all_applicable(cart, context)
            if self.stacking_policy == StackingPolicy.EXCLUSIVE_BEST_FOR_CUSTOMER:
                all_discounts, skipped_combination = self._resolve_exclusive_best(
                    candidates
                )
            elif self.stacking_policy == StackingPolicy.EXCLUSIVE_PRIORITY:
                all_discounts, skipped_combination = self._resolve_exclusive_priority(
                    candidates
                )
            else:
                raise ValueError(f"Unknown stacking policy: {self.stacking_policy!r}")

        raw_discount_total = Money(Decimal("0"))
        if all_discounts:
            raw_discount_total = sum(
                (d.amount for d in all_discounts),
                Money(Decimal("0")),
            )

        discount_total = min(subtotal, raw_discount_total)
        total = subtotal - discount_total

        return PriceSummary(
            subtotal=subtotal,
            discount_total=discount_total,
            total=total,
            applied_discounts=all_discounts,
            not_applicable_promotion_ids=tuple(not_applicable),
            skipped_due_to_combination_ids=tuple(skipped_combination),
        )
