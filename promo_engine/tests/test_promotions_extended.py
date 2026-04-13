# ABOUTME: Constraints, caps, and additional promotion types

import unittest
from datetime import datetime, time, timedelta, timezone
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
    BuyXPayYPromotion,
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

    def test_valid_from_to_window(self) -> None:
        c = PromotionConstraints(
            valid_from=datetime(2024, 6, 1, 0, 0, tzinfo=UTC),
            valid_to=datetime(2024, 6, 30, 23, 59, 59, tzinfo=UTC),
        )
        mid = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)
        self.assertTrue(c.allows(PricingContext(mid, "o", "c", set())))
        self.assertFalse(
            c.allows(PricingContext(datetime(2024, 5, 1, 12, 0, tzinfo=UTC), "o", "c", set()))
        )

    def test_january_promo_jan10_applies_feb1_does_not(self) -> None:
        """Acceptance: promo Jan 1–Jan 31; Jan 10 in window, Feb 1 out."""
        c = PromotionConstraints(
            valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            valid_to=datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC),
        )
        self.assertTrue(
            c.allows(PricingContext(datetime(2026, 1, 10, 12, 0, tzinfo=UTC), "o", "c", set()))
        )
        self.assertFalse(
            c.allows(PricingContext(datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC), "o", "c", set()))
        )

    def test_window_inclusive_at_valid_from_and_valid_to(self) -> None:
        vf = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        vt = datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC)
        c = PromotionConstraints(valid_from=vf, valid_to=vt)
        self.assertTrue(c.allows(PricingContext(vf, "o", "c", set())))
        self.assertTrue(c.allows(PricingContext(vt, "o", "c", set())))

    def test_window_rejects_immediately_after_valid_to(self) -> None:
        vt = datetime(2026, 1, 31, 12, 0, 0, tzinfo=UTC)
        c = PromotionConstraints(
            valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            valid_to=vt,
        )
        self.assertFalse(
            c.allows(PricingContext(vt + timedelta(seconds=1), "o", "c", set()))
        )

    def test_window_rejects_immediately_before_valid_from(self) -> None:
        vf = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
        c = PromotionConstraints(
            valid_from=vf,
            valid_to=datetime(2026, 1, 31, 0, 0, 0, tzinfo=UTC),
        )
        self.assertFalse(
            c.allows(PricingContext(vf - timedelta(seconds=1), "o", "c", set()))
        )

    def test_mixed_naive_context_and_aware_bounds_raises(self) -> None:
        c = PromotionConstraints(
            valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            valid_to=datetime(2026, 1, 31, 0, 0, 0, tzinfo=UTC),
        )
        naive_now = datetime(2026, 1, 10, 12, 0, 0)
        with self.assertRaises(ValueError):
            c.allows(PricingContext(naive_now, "o", "c", set()))

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

    def test_gold_segment_tags_include_gold_allows(self) -> None:
        c = PromotionConstraints(required_customer_tags=frozenset({"gold"}))
        self.assertTrue(c.allows(ctx(tags={"gold", "newsletter"})))

    def test_gold_segment_tags_exclude_gold_denies(self) -> None:
        c = PromotionConstraints(required_customer_tags=frozenset({"gold"}))
        self.assertFalse(c.allows(ctx(tags={"silver"})))


class TestCustomerSegmentationGoldEngine(unittest.TestCase):
    """Gold segment promos use PricingContext.customer_tags."""

    def test_gold_promo_applies_when_context_includes_gold(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(1), Money(Decimal("10.00")))])
        promo = PercentOffSkusPromotion(
            PromotionId("GOLD15"),
            Percentage(Decimal("15")),
            frozenset({Sku("SKU_A")}),
            constraints=PromotionConstraints(
                required_customer_tags=frozenset({"gold"}),
            ),
        )
        engine = PromotionEngine([promo])
        gold_ctx = PricingContext(
            datetime(2024, 6, 3, 12, 0, tzinfo=UTC),
            "online",
            "c1",
            {"gold"},
        )
        summary = engine.price(cart, gold_ctx)
        self.assertEqual(summary.discount_total, Money(Decimal("1.50")))

    def test_gold_promo_not_applied_without_gold_tag(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(1), Money(Decimal("10.00")))])
        promo = PercentOffSkusPromotion(
            PromotionId("GOLD15"),
            Percentage(Decimal("15")),
            frozenset({Sku("SKU_A")}),
            constraints=PromotionConstraints(
                required_customer_tags=frozenset({"gold"}),
            ),
        )
        engine = PromotionEngine([promo])
        silver_ctx = PricingContext(
            datetime(2024, 6, 3, 12, 0, tzinfo=UTC),
            "online",
            "c1",
            {"silver"},
        )
        summary = engine.price(cart, silver_ctx)
        self.assertEqual(summary.discount_total, Money(Decimal("0.00")))
        self.assertEqual(summary.not_applicable_promotion_ids, (PromotionId("GOLD15"),))


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


class TestBuyXPayY(unittest.TestCase):
    """Buy X pay Y (e.g. 3-for-2): acceptance examples and validation."""

    def test_three_for_two_three_units(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(3), Money(Decimal("10.00")))])
        promo = BuyXPayYPromotion(PromotionId("3F2"), Sku("SKU_A"), buy_x=3, pay_y=2)
        summary = PromotionEngine([promo]).price(cart, ctx())
        self.assertEqual(summary.discount_total, Money(Decimal("10.00")))

    def test_three_for_two_four_units(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(4), Money(Decimal("10.00")))])
        promo = BuyXPayYPromotion(PromotionId("3F2"), Sku("SKU_A"), buy_x=3, pay_y=2)
        summary = PromotionEngine([promo]).price(cart, ctx())
        self.assertEqual(summary.discount_total, Money(Decimal("10.00")))

    def test_three_for_two_six_units(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(6), Money(Decimal("10.00")))])
        promo = BuyXPayYPromotion(PromotionId("3F2"), Sku("SKU_A"), buy_x=3, pay_y=2)
        summary = PromotionEngine([promo]).price(cart, ctx())
        self.assertEqual(summary.discount_total, Money(Decimal("20.00")))

    def test_invalid_pay_y_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BuyXPayYPromotion(PromotionId("X"), Sku("A"), buy_x=3, pay_y=3)
        with self.assertRaises(ValueError):
            BuyXPayYPromotion(PromotionId("X"), Sku("A"), buy_x=3, pay_y=0)
        with self.assertRaises(ValueError):
            BuyXPayYPromotion(PromotionId("X"), Sku("A"), buy_x=1, pay_y=1)


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


class TestDateWindowEngineIntegration(unittest.TestCase):
    def test_percent_off_engine_respects_january_date_window(self) -> None:
        product = Product(Sku("SKU_A"), "A", "c")
        cart = Cart([LineItem(product, Quantity(1), Money(Decimal("10.00")))])
        promo = PercentOffSkusPromotion(
            PromotionId("JAN10"),
            Percentage(Decimal("10")),
            frozenset({Sku("SKU_A")}),
            constraints=PromotionConstraints(
                valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
                valid_to=datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC),
            ),
        )
        engine = PromotionEngine([promo])
        jan_ctx = PricingContext(
            datetime(2026, 1, 10, 12, 0, tzinfo=UTC), "online", "C1", set()
        )
        feb_ctx = PricingContext(
            datetime(2026, 2, 1, 12, 0, tzinfo=UTC), "online", "C1", set()
        )
        self.assertEqual(engine.price(cart, jan_ctx).discount_total, Money(Decimal("1.00")))
        self.assertEqual(engine.price(cart, feb_ctx).discount_total, Money(Decimal("0.00")))


if __name__ == "__main__":
    unittest.main()
