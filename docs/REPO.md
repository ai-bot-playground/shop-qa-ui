# Repo selection

## Decision: Satchmo (`dokterbob/satchmo`)

Abandoned Python/Django e-commerce platform (active ~2007–2013).
Fork: https://github.com/Acc-Ai-Hackaton/satchmo.git
Local: `legacy-satchmo/`

**Confirmed — all three business domains present:**

| Example module | Satchmo equivalent | Key files |
|---|---|---|
| `billing.py` — VAT, discount codes | Payment + Tax + Discount | `payment/models.py`, `tax/modules/percent/processor.py`, `product/models.py` (`Discount`) |
| `inventory.py` — stock reserve/release | Product stock | `product/models.py` (`Product`, `ProductPriceLookup`), `product/utils.py` |
| `orders.py` — process/cancel, status codes | Order processing | `satchmo_store/shop/models.py` (`Order`, `OrderStatus`, `OrderItem`) |

**Legacy smells confirmed:**

| Smell | Example | Location |
|---|---|---|
| Python 2 syntax | `except KeyedcacheError, nce:` / `<>` operator | `shop/models.py:61`, `payment/models.py:123` |
| Magic string status codes | `'Temp','New','Blocked','In Process','Billed','Shipped','Complete','Cancelled'` | `shop/models.py` ORDER_STATUS |
| Magic numbers | `qty = round_decimal('10000.0')` (fake infinite stock), `round_decimal('-1.0')` | `product/utils.py:87,89` |
| No docstrings | `force_recalculate_total()` — 100+ line method, zero docs | `shop/models.py:881` |
| TODO in production | `# TODO: Validate against logged-in user.` | `shop/models.py:586` |
| Assertion-based errors | `assert(self._calculated)` — crashes if discount not pre-calculated | `product/models.py:580` |
| Cryptic variable names | `nce`, `cc`, `pct` | throughout |
| Complex undocumented algorithm | `apply_even_split()` — multi-pass discount distribution, no comments | `product/models.py:610` |
| Signal-based side effects | `order_success.send()` — no guaranteed execution order | `shop/models.py:1005` |

**Target modules for demo (business logic only):**
- `satchmo/apps/payment/models.py` — payment options, CC encryption
- `satchmo/apps/payment/modules/base.py` — processor base class
- `satchmo/apps/tax/modules/percent/processor.py` — tax calculation
- `satchmo/apps/product/models.py` — Discount model + stock
- `satchmo/apps/product/utils.py` — stock pricing, auto-discounts
- `satchmo/apps/satchmo_store/shop/models.py` — Order, OrderItem, OrderStatus

**Exclude:** migrations, templates, static files, l10n, urls.py, admin.py

## Rejected alternatives

| Repo | Reason rejected |
|---|---|
| Roundup | No billing/inventory/orders domain |
| beancount v2 | Financial only, no orders/inventory |
| ERPNext v7-v8 | Too large for 3-min demo; needs manual slicing |
| stephenmcd/cartridge | Not explored — Satchmo confirmed sufficient |
