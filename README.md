# Promotion engine (Python kata)

Small library for pricing a shopping cart with promotions: **percentage off selected SKUs**, per-line `Money` rounding (half-up, two decimals), multi-promotion stacking, and checkout totals when nominal discounts exceed the cart subtotal.

Normative behavior is described in [spec.md](spec.md). Implementation prompts and checklist live in [plan.md](plan.md).

## Requirements

- Python 3.12+
- [Poetry](https://python-poetry.org/) for dependency management and builds

## Setup

```bash
cd promotion-engine-kata/python
poetry install --with dev
```

## Tests

```bash
# stdlib
poetry run python -m unittest discover -s promo_engine/tests -p 'test_*.py' -v

# pytest (dev dependency)
poetry run pytest
```

## Build

```bash
poetry build
```

## Package layout

| Module | Purpose |
|--------|---------|
| `promo_engine.domain` | `Money`, cart types, `PriceSummary`, `AppliedDiscount` |
| `promo_engine.promotions` | `Promotion` ABC, `PercentOffSkusPromotion` |
| `promo_engine.engine` | `PromotionEngine.price` |
