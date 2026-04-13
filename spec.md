# Promotion engine — baseline specification

This document is normative for the Python package in this directory (`promo_engine`). It describes the baseline pricing engine: cart subtotals, percentage discounts on selected SKUs, multi-promotion application, money rounding, and explainability.

## Scope

- **In scope**: `PromotionEngine` orchestration and `StackingPolicy`; `PromotionConstraints` (time window, weekday, daypart, customer tags); `PercentOffSkusPromotion` (percentage off SKUs, optional `max_discount`); `FixedAmountOffPromotion`; `ThresholdPromotion` (spend threshold, fixed reward); `BuyXGetYPromotion` (bundle free units at cheapest unit prices); `BuyXPayYPromotion` (buy X pay Y / e.g. 3-for-2); `Money` / cart math; `PriceSummary` and `AppliedDiscount` explainability.
- **Not covered here**: `PricingContext.channel` targeting (field exists for future use).

## Types (glossary)

- **Money**: Decimal amount quantized to **two decimal places** using **ROUND_HALF_UP** on construction and on results of `Money` arithmetic that returns `Money`. `str(Money(...))` uses a **€** prefix and two fractional digits for this kata (presentation only).
- **Cart**: List of **line items**; each line has `product` (with `sku`), `quantity` (non-negative integer), and `unit_price` (`Money`).
- **PricingContext**: Passed into `PromotionEngine.price`. Promotions may read **`now`** and **`customer_tags`** via optional `PromotionConstraints`; other fields are reserved for future rules.
- **AppliedDiscount**: One applied instance from a promotion: `promotion_id`, `amount` (`Money`, nominal for that promotion), `target` (`"line"` for this baseline), `details` (human-readable), optional `allocations` (`Sku` → `Money`, nominal per SKU, aggregated across lines).

## Subtotal

For each line, **line subtotal** = `unit_price × quantity` as `Money`.

**Cart subtotal** = sum of line subtotals (`Money`).

## PromotionConstraints

Optional filters (all unset ⇒ no restriction):

- **`valid_from` / `valid_to`**: when set, `PricingContext.now` must satisfy `valid_from <= now <= valid_to` (inclusive at both ends: rejected only if `now < valid_from` or `now > valid_to`). Choose **`valid_to` as the last included instant** (for example end-of-day on the last calendar day) so “Feb 1” is outside a January-only promo. **`valid_from` / `valid_to` and `now` must all be timezone-aware or all naive**; mixing raises `ValueError` in `PromotionConstraints.allows`.
- **`allowed_weekdays`**: if set, `now.weekday()` must be in the set (`datetime` convention: Monday = 0 … Sunday = 6).
- **`daypart_start` / `daypart_end`**: both required if either is set; `now.time()` must fall in that inclusive range on the clock (supports overnight windows when start > end).
- **`required_customer_tags`**: if non-empty, must be a **subset** of `context.customer_tags`.

## Discount: percent off selected SKUs

For each promotion configuration `(promotion_id, percentage, eligible_skus)` plus optional **`constraints`**, **`max_discount`**:

1. **Applicability**: `constraints.allows(context)` and at least one cart line eligible by SKU/quantity as below.
2. A line is **eligible** if `quantity > 0` and `line.product.sku` is in `eligible_skus`.
3. For each eligible line, **line discount** = `unit_price × (quantity × percentage_as_decimal)` as `Money` (half-up at each `Money` result).
4. **Allocations**: Discounts from all lines with the same SKU are **aggregated** into a single `Money` per `Sku`.
5. If **`max_discount`** is set and the raw sum exceeds it, **amount and per-SKU allocations** are scaled proportionally to that cap (with half-up `Money` quantization and a small drift correction so totals match).

If there are no eligible lines, the promotion is not applicable (no `AppliedDiscount` from it).

**Explainability** for this promotion must be recoverable from:

- `promotion_id`, and
- `details` (must convey **percentage** and **affected SKUs** in human-readable form), and
- `allocations` (per-SKU nominal amounts).

## Fixed amount off cart

`FixedAmountOffPromotion`: if `constraints` pass, cart subtotal `> 0`, and subtotal `>= minimum_subtotal` when that minimum is set, apply a single cart-level `AppliedDiscount` with `target="cart"` and fixed `amount_off`.

## Threshold (spend X, save Y)

`ThresholdPromotion`: if `constraints` pass and cart subtotal `>= threshold`, apply fixed `reward` as one cart-level `AppliedDiscount` (`target="cart"`).

## Buy X get Y (same SKU)

`BuyXGetYPromotion`: parameters `buy_x` and `get_y` (both ≥ 1). For `target_sku`, total quantity across lines determines how many full bundles of size `buy_x + get_y` exist. For each bundle, **`get_y`** units are treated as free; discount value is the sum of the **cheapest** free unit prices (expanded per quantity, sorted by `Money`, multi-line safe).

## Buy X pay Y (same SKU, e.g. 3-for-2)

`BuyXPayYPromotion`: parameters **`buy_x`** (≥ 2) and **`pay_y`** with **`1 <= pay_y < buy_x`**. Applies only to **`target_sku`**. Pool quantity `Q` and line subtotals for that SKU.

- **`number_of_groups`** = `Q // buy_x` (integer division; partial groups do not count).
- **`free_slots`** = `(buy_x - pay_y) * number_of_groups` (equivalent number of free items).
- **Discount** (single unit price `P` on all lines): `P * free_slots` = `P * (buy_x - pay_y) * number_of_groups`, matching “`(X−Y)` free per group”.
- **Discount** (mixed unit prices on the same SKU): **`pool_subtotal * free_slots / Q`** where `pool_subtotal` is the sum of line subtotals for `target_sku` (same numeric result as uniform `P` when all units share one price).

Examples (€10 unit, `buy_x=3`, `pay_y=2`): 3 units → €10 off; 4 units → one full group → still €10 off; 6 units → two groups → €20 off.

## StackingPolicy (`PromotionEngine`)

`PromotionEngine` takes an optional **`stacking_policy`** (`StackingPolicy` in `promo_engine.domain`, default **`STACK`**):

- **`STACK`**: After sorting by **`priority` descending** then **`id`**, walk in order: apply each applicable promotion; if **`stackable` is False** for a promotion that runs, **later promotions are skipped** (same combination rule as before). Sum all produced discounts (then checkout cap).
- **`EXCLUSIVE_BEST_FOR_CUSTOMER`**: **Every** applicable promotion is evaluated (`apply` called). The engine keeps only the candidate whose **total nominal discount** (sum of its `AppliedDiscount.amount`) is **largest**. Ties: higher **`priority`**, then lexicographically smaller **`promotion id`**, then earlier in the sorted list. Other applicable promotions are listed in **`skipped_due_to_combination_ids`**.
- **`EXCLUSIVE_PRIORITY`**: Same full evaluation order; the **first** applicable promotion in that order that returns a **non-empty** discount list wins; all later applicable promotions are skipped (their ids in **`skipped_due_to_combination_ids`**).

Example (3 × `SKU_A` @ €10, 10% off vs 3-for-2): nominal discounts **€3** vs **€10** — **STACK** applies both (€13); **EXCLUSIVE_BEST_FOR_CUSTOMER** applies only 3-for-2 (€10); **EXCLUSIVE_PRIORITY** with sort order putting 10% first applies only 10% (€3).

## Multi-promotion behavior

Each promotion exposes **`priority`** (int, default `0`) and **`stackable`** (bool, default `True`). Sorting is always **`priority` descending**, then **`id`** ascending.

- **STACK mode**: **`stackable == True`**: discount is applied and processing continues. **`stackable == False`**: discount is applied, then **no further promotions** are considered (their ids go to **`skipped_due_to_combination_ids`** if they would have been applicable).
- **Exclusive modes**: per-promotion **`stackable`** does not early-stop the evaluation pass; the **policy** chooses the winner set as above.
- **Tracing**: `PriceSummary.not_applicable_promotion_ids` lists promotions for which `is_applicable` was false. `PriceSummary.skipped_due_to_combination_ids` lists promotions skipped due to **non-stackable** (STACK) or **stacking policy** (exclusive modes).
- **Raw discount sum** = sum of `amount` over all `AppliedDiscount` entries actually produced (as `Money`).

## Checkout totals (authoritative)

Let `S` = cart subtotal and `R` = raw discount sum.

- **`discount_total`** = `min(S, R)`.
- **`total`** = `S - discount_total`.

Therefore **`total` is never negative**, and **`discount_total` never exceeds `subtotal`**.

### Authoritative fields

`PriceSummary.subtotal`, `PriceSummary.discount_total`, and `PriceSummary.total` are **authoritative for checkout**.

When `R > S` (e.g. stacked promotions), **`discount_total` is capped at `subtotal`** but each `AppliedDiscount.amount` remains the **nominal** discount computed by that promotion. So **`sum(d.amount for d in applied_discounts)` may be greater than `discount_total`**. Consumers must use `discount_total` and `total` for payable amounts; `applied_discounts` explain what each promotion computed.

## Acceptance example (must remain covered by tests)

Cart:

- 2 × `SKU_A` at €10.00 each
- 1 × `SKU_B` at €5.00

Promotion: **10%** off **`SKU_A`** only.

Expected:

- **Subtotal**: €25.00  
- **Discount** (10% of line A only): 2 × €10.00 × 10% = **€2.00**  
- **Total**: **€23.00**  

Explainability includes promotion id, **10%**, and **SKU_A** (and must not attribute discount to `SKU_B`).

## Edge cases (expected test coverage)

- **Per-line rounding**: Discount is computed per eligible line (or equivalent aggregation that preserves line-level `Money` rounding), not as a single unrounded aggregate on the whole cart subtotal × rate unless it matches those line results.
- **Same SKU, multiple lines**: Allocations aggregate per SKU for one promotion application.
- **Over-discount**: When nominal discounts sum above subtotal, `discount_total == subtotal`, `total == €0.00`, and `subtotal - discount_total == total`.

## Implementation alignment

This spec matches the intended behavior of:

- `promo_engine.domain` (`Money`, `Cart`, `LineItem`, `PriceSummary`, `AppliedDiscount`, `StackingPolicy`, …)
- `promo_engine.promotions` (`PromotionConstraints`, `PercentOffSkusPromotion`, `FixedAmountOffPromotion`, `ThresholdPromotion`, `BuyXGetYPromotion`, `BuyXPayYPromotion`)
- `promo_engine.engine.PromotionEngine`

`PromotionEngine.price` implements checkout totals exactly as in **Checkout totals (authoritative)**: it sums nominal `AppliedDiscount.amount` values into a raw total `R`, then sets `discount_total = min(subtotal, R)` and `total = subtotal - discount_total` (see `promo_engine/engine.py`). That matches the formulas above, including when `R > subtotal`.

Where the implementation differs from this document, either the code or this spec should be updated so they agree.

## Running tests

From this directory (`promotion-engine-kata/python`). Pytest is wired via **`[tool.pytest.ini_options]`** in [`pyproject.toml`](pyproject.toml) (`testpaths`, `pythonpath`); there is no separate `pytest.ini`, so nothing duplicates a second on-disk config.

Install dev tools (includes pytest) once:

- `poetry install --with dev`

Then either:

- **unittest** (stdlib only): `python -m unittest discover -s promo_engine/tests -p 'test_*.py' -v`  
  or with Poetry: `poetry run python -m unittest discover -s promo_engine/tests -p 'test_*.py' -v`
- **pytest**: `poetry run pytest` (or `pytest` if your environment already has pytest on `PATH`)
