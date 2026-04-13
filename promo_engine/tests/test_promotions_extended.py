# ABOUTME: Constraints, caps, and additional promotion types

import unittest
from datetime import datetime, time, timezone
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
from promo_engine.promotions import (
    BuyXGetYPromotion,
    FixedAmountOffPromotion,
    PercentOffSkusPromotion,
    PromotionConstraints,
    ThresholdPromotion,
)

UTC = timezone.utc


def ctx(
    when: datetime | None = None,
    *,
    tags: set[str] | None = None,
) -> PricingContext:
    return PricingContext(
        now=when or datetime(2024, 6, 3, 12, 0, 0, tzinfo=UTC),
        channel="online",
        customer_id="C1",
        customer_tags=tags if tags is not None else set(),
    )


class TestPromotionConstraints(unittest.TestCase):
    def test_empty_constraints_allow_all(self) -> None:
        self.assertTrue(PromotionConstraints().allows(ctx()))

    def test_daypart_requires_both_bounds(self) -> None:
        with self.assertRaises(ValueError):
            PromotionConstraints(daypart_start=time(9, 0), daypart_end=None)

    def test_valid_from_until_window(self) -> None:
        c = PromotionConstraints(
            valid_from=datetime(2024, 6, 1, 0, 0, tzinfo=UTC),
            valid_until=datetime(2024, 6, 30, 23, 59, 59, tzinfo=UTC),
        )
        mid = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)
        self.assertTrue(c.allows(PricingContext(mid, "o", "c", set())))
        self.assertFalse(
            c.allows(PricingContext(datetime(2024, 5, 1, 12, 0, tzinfo=UTC), "o", "c", set()))
        )

    def test_allowed_weekdays(self) -> None:
        # 2024-06-03 is Monday (0)
        mon_only = PromotionConstraints(allowed_weekdays=frozenset({0}))
        self.assertTrue(
            mon_only.allows(
                PricingContext(datetime(2024, 6, 3, 12, 0, tzinfo=UTC), "o", "c", set())
            )
        )
        self.assertFalse(
            mon_only.allows(
                PricingContext(datetime(2024, 6, 4, 12, 0, tzinfo=UTC), "o", "c", set())
            )
        )

    def test_daypart_inclusive(self) -> None:
        c = PromotionConstraints(
            daypart_start=time(9, 0),
            daypart_end=time(17, 0),
        )
        self.assertTrue(
            c.allows(
                PricingContext(datetime(2024, 6, 3, 12, 0, tzinfo=UTC), "o", "c", set())
            )
        )
        self.assertFalse(
            c.allows(
                PricingContext(datetime(2024, 6, 3, 18, 0, tzinfo=UTC), "o", "c", set())
            )
        )

    def test_required_customer_tags_subset(self) -> None:
        c = PromotionConstraints(required_customer_tags=frozenset({"vip", "de"}))
        self.assertTrue(c.allows(ctx(tags={"vip", "de", "other"})))
        self.assertFalse(c.allows(ctx(tags={"vip"})))


class TestPercentOffMaxDiscount(unittest.TestCase):
    def test_max_discount_caps_amount_and_allocations(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(2), Money(Decimal("10.00")))])
        promo = PercentOffSkusPromotion(
            PromotionId("CAP"),
            Percentage(Decimal("50")),
            frozenset({Sku("SKU_A")}),
            max_discount=Money(Decimal("5.00")),
        )
        summary = PromotionEngine([promo]).price(cart, ctx())
        self.assertEqual(summary.applied_discounts[0].amount, Money(Decimal("5.00")))
        ad = summary.applied_discounts[0]
        assert ad.allocations is not None
        self.assertEqual(ad.allocations[Sku("SKU_A")], Money(Decimal("5.00")))


class TestFixedAmountOff(unittest.TestCase):
    def test_fixed_off_cart(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(1), Money(Decimal("40.00")))])
        promo = FixedAmountOffPromotion(
            PromotionId("FIX"),
            Money(Decimal("5.00")),
            minimum_subtotal=Money(Decimal("30.00")),
        )
        summary = PromotionEngine([promo]).price(cart, ctx())
        self.assertEqual(summary.discount_total, Money(Decimal("5.00")))
        self.assertEqual(summary.total, Money(Decimal("35.00")))
        self.assertEqual(summary.applied_discounts[0].target, "cart")


class TestThresholdPromotion(unittest.TestCase):
    def test_spend_threshold_triggers_reward(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(1), Money(Decimal("60.00")))])
        promo = ThresholdPromotion(
            PromotionId("TH"),
            threshold=Money(Decimal("50.00")),
            reward=Money(Decimal("5.00")),
        )
        summary = PromotionEngine([promo]).price(cart, ctx())
        self.assertEqual(summary.discount_total, Money(Decimal("5.00")))
        self.assertEqual(summary.total, Money(Decimal("55.00")))

    def test_below_threshold_not_applicable(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(1), Money(Decimal("40.00")))])
        promo = ThresholdPromotion(
            PromotionId("TH"),
            threshold=Money(Decimal("50.00")),
            reward=Money(Decimal("5.00")),
        )
        self.assertFalse(promo.is_applicable(cart, ctx()))


class TestBuyXGetY(unittest.TestCase):
    def test_invalid_bundle_sizes_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BuyXGetYPromotion(PromotionId("X"), Sku("A"), buy_x=0, get_y=1)

    def test_buy_two_get_one_free_single_price(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(3), Money(Decimal("10.00")))])
        promo = BuyXGetYPromotion(PromotionId("B2G1"), Sku("SKU_A"), buy_x=2, get_y=1)
        summary = PromotionEngine([promo]).price(cart, ctx())
        self.assertEqual(summary.discount_total, Money(Decimal("10.00")))
        self.assertEqual(summary.total, Money(Decimal("20.00")))

    def test_buy_two_get_one_cheapest_free_across_lines(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart(
            [
                LineItem(product, Quantity(1), Money(Decimal("10.00"))),
                LineItem(product, Quantity(2), Money(Decimal("8.00"))),
            ]
        )
        promo = BuyXGetYPromotion(PromotionId("B2G1"), Sku("SKU_A"), buy_x=2, get_y=1)
        summary = PromotionEngine([promo]).price(cart, ctx())
        self.assertEqual(summary.discount_total, Money(Decimal("8.00")))


class TestConstraintsWithPercentOff(unittest.TestCase):
    def test_tags_gate_percent_off(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(1), Money(Decimal("10.00")))])
        promo = PercentOffSkusPromotion(
            PromotionId("VIP10"),
            Percentage(Decimal("10")),
            frozenset({Sku("SKU_A")}),
            constraints=PromotionConstraints(required_customer_tags=frozenset({"vip"})),
        )
        self.assertFalse(promo.is_applicable(cart, ctx(tags=set())))
        self.assertTrue(promo.is_applicable(cart, ctx(tags={"vip"})))


if __name__ == "__main__":
    unittest.main()
