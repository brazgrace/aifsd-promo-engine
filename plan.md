# Promotion engine — implementation plan

Executable prompts for the baseline engine (see [spec.md](spec.md)). Mark each prompt **Completed** when its acceptance criteria are met, tests pass, and changes are committed.

## Prompt checklist

| # | Prompt | Status |
|---|--------|--------|
| 1 | [Spec file only](#prompt-1--spec-file-only) | Completed |
| 2 | [TDD Money EUR display](#prompt-2--tdd-money-eur-display) | Not started |
| 3 | [TDD engine capping](#prompt-3--tdd-engine-capping) | Not started |
| 4 | [Regression + consistency](#prompt-4--regression--consistency) | Not started |
| 5 | [Optional pytest](#prompt-5--optional-pytest) | Not started |

---

## Prompt 1 — Spec file only

**Status: Completed**

Normative requirements are in [spec.md](spec.md) at this project root (next to `pyproject.toml`). No code changes were required for this prompt.

---

## Prompt 2 — TDD Money EUR display

**Status: Not started**

```text
TDD: In promo_engine/domain.py, Money.__str__ must format as Euro with the euro sign, e.g. €42.50 (currency symbol + amount with two decimals). Update promo_engine/tests/test_domain.py test_money_str (and any other test asserting $) to expect €. Implement the minimal change to make tests pass. Do not change Money quantization rules.
```

---

## Prompt 3 — TDD engine capping

**Status: Not started**

```text
TDD: Extend promo_engine/engine.py PromotionEngine.price so that after collecting applied_discounts, raw = sum(d.amount), discount_total = min(subtotal, raw), total = subtotal - discount_total. Preserve existing behavior when raw <= subtotal. Add a new unittest TestCase (either in tests/test_engine.py or tests/test_engine_cap.py) using StubPromotion with two promotions whose nominal discounts exceed a small cart subtotal; assert discount_total equals subtotal, total is Money("0.00"), and subtotal - discount_total == total. Wire no new public APIs; keep AppliedDiscount objects unchanged.
```

---

## Prompt 4 — Regression + consistency

**Status: Not started**

```text
Run the full test suite for promo_engine (unittest discovery). Fix any failures caused by string expectations or total math. Optionally update dollar-sign wording in comments to Euro where it refers to user-visible formatting. Ensure spec.md mentions the capping behavior matches the implementation. No new orphaned files beyond spec.md and any test file you added in Prompt 3.
```

---

## Prompt 5 — Optional pytest

**Status: Not started**

```text
If we want pytest support: add a minimal pytest.ini or pyproject [tool.pytest.ini_options] and document in spec.md how to run tests with either python -m unittest or pytest. Only do this if it does not duplicate CI configuration; keep default developer workflow working.
```
