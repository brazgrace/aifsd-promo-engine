# ABOUTME: PercentOffSkusPromotion — README acceptance and edge cases

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from promo_engine.domain import (
    Cart,
    LineItem,
    Money,
    Percentage,
    PricingContext,
    Product,
    PromotionId,
    Quantity,
    Sku,
)
from promo_engine.engine import PromotionEngine
from promo_engine.promotions import PercentOffSkusPromotion


def ctx() -> PricingContext:
    return PricingContext(
        now=datetime.now(timezone.utc),
        channel="online",
        customer_id="CUST001",
        customer_tags=set(),
    )


class TestPercentOffSkusPromotion(unittest.TestCase):
    """Step 1: percentage discount per eligible line."""

    def test_readme_acceptance_10_percent_off_sku_a(self) -> None:
        """2×SKU_A @ €10, 1×SKU_B @ €5 → subtotal €25, €2 off A, total €23."""
        product_a = Product(Sku("SKU_A"), "A", "cat")
        product_b = Product(Sku("SKU_B"), "B", "cat")
        cart = Cart(
            [
                LineItem(product_a, Quantity(2), Money(Decimal("10.00"))),
                LineItem(product_b, Quantity(1), Money(Decimal("5.00"))),
            ]
        )
        promo = PercentOffSkusPromotion(
            promotion_id=PromotionId("PROMO-10-A"),
            percentage=Percentage(Decimal("10")),
            eligible_skus=frozenset({Sku("SKU_A")}),
        )
        engine = PromotionEngine([promo])
        summary = engine.price(cart, ctx())

        self.assertEqual(summary.subtotal, Money(Decimal("25.00")))
        self.assertEqual(summary.discount_total, Money(Decimal("2.00")))
        self.assertEqual(summary.total, Money(Decimal("23.00")))
        self.assertEqual(len(summary.applied_discounts), 1)

        ad = summary.applied_discounts[0]
        self.assertEqual(ad.promotion_id, PromotionId("PROMO-10-A"))
        self.assertEqual(ad.amount, Money(Decimal("2.00")))
        self.assertEqual(ad.target, "line")
        self.assertIsNotNone(ad.allocations)
        assert ad.allocations is not None
        self.assertEqual(ad.allocations.get(Sku("SKU_A")), Money(Decimal("2.00")))
        self.assertNotIn(Sku("SKU_B"), ad.allocations)

        self.assertIn("PROMO-10-A", ad.details)
        self.assertIn("10%", ad.details)
        self.assertIn("SKU_A", ad.details)

    def test_not_applicable_ineligible_skus_only(self) -> None:
        """Cart with no eligible SKUs → engine applies no discount."""
        product_b = Product(Sku("SKU_B"), "B", "cat")
        cart = Cart([LineItem(product_b, Quantity(1), Money(Decimal("5.00")))])
        promo = PercentOffSkusPromotion(
            promotion_id=PromotionId("PROMO-A-ONLY"),
            percentage=Percentage(Decimal("10")),
            eligible_skus=frozenset({Sku("SKU_A")}),
        )
        self.assertFalse(promo.is_applicable(cart, ctx()))

        engine = PromotionEngine([promo])
        summary = engine.price(cart, ctx())
        self.assertEqual(summary.discount_total, Money(Decimal("0")))
        self.assertEqual(len(summary.applied_discounts), 0)

    def test_per_line_rounding_not_same_as_subtotal_times_rate(self) -> None:
        """Three lines @ €0.07, 10% each: per-line rounds to €0.01 × 3 = €0.03, not €0.02 on €0.21."""
        product_a = Product(Sku("SKU_A"), "A", "cat")
        cart = Cart(
            [
                LineItem(product_a, Quantity(1), Money(Decimal("0.07"))),
                LineItem(product_a, Quantity(1), Money(Decimal("0.07"))),
                LineItem(product_a, Quantity(1), Money(Decimal("0.07"))),
            ]
        )
        promo = PercentOffSkusPromotion(
            promotion_id=PromotionId("ROUND-TEST"),
            percentage=Percentage(Decimal("10")),
            eligible_skus=frozenset({Sku("SKU_A")}),
        )
        engine = PromotionEngine([promo])
        summary = engine.price(cart, ctx())

        self.assertEqual(summary.subtotal, Money(Decimal("0.21")))
        self.assertEqual(summary.discount_total, Money(Decimal("0.03")))
        self.assertEqual(summary.total, Money(Decimal("0.18")))

    def test_duplicate_sku_lines_aggregate_allocations(self) -> None:
        """Two lines same SKU: allocations sum per-SKU bucket."""
        product_a = Product(Sku("SKU_A"), "A", "cat")
        cart = Cart(
            [
                LineItem(product_a, Quantity(1), Money(Decimal("10.00"))),
                LineItem(product_a, Quantity(1), Money(Decimal("10.00"))),
            ]
        )
        promo = PercentOffSkusPromotion(
            promotion_id=PromotionId("AGG"),
            percentage=Percentage(Decimal("10")),
            eligible_skus=frozenset({Sku("SKU_A")}),
        )
        engine = PromotionEngine([promo])
        summary = engine.price(cart, ctx())

        ad = summary.applied_discounts[0]
        assert ad.allocations is not None
        self.assertEqual(ad.allocations[Sku("SKU_A")], Money(Decimal("2.00")))
        self.assertEqual(ad.amount, Money(Decimal("2.00")))

    def test_single_line_10_01_at_10_percent_rounds_per_line(self) -> None:
        """10.01 × 10% quantizes to 1.00 (per-line Money rounding)."""
        product_a = Product(Sku("SKU_A"), "A", "cat")
        cart = Cart(
            [LineItem(product_a, Quantity(1), Money(Decimal("10.01")))]
        )
        promo = PercentOffSkusPromotion(
            promotion_id=PromotionId("PCT"),
            percentage=Percentage(Decimal("10")),
            eligible_skus=frozenset({Sku("SKU_A")}),
        )
        summary = PromotionEngine([promo]).price(cart, ctx())
        self.assertEqual(summary.applied_discounts[0].amount, Money(Decimal("1.00")))


if __name__ == "__main__":
    unittest.main()
