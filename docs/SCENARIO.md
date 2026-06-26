# Demo scenario

## Concept

Run the same 10-question evaluation set as `sample/questions.csv` but against real Satchmo source code.
This lets us show: "here's a real abandoned repo — our system answers the same class of questions a new developer would ask."

## Question mapping (updated — Satchmo explored)

| Q# | Original question (examples) | Satchmo equivalent | Target file | Key symbol |
|---|---|---|---|---|
| Q01 | process_order return when all out-of-stock? | What status does an order get when no items can be reserved? | `satchmo_store/shop/models.py` | `ORDER_STATUS`, `add_status()` |
| Q02 | Which function applies discount? | Which method calculates a discount on an order? | `product/models.py` | `Discount.calc()`, `apply_percentage()` |
| Q03 | Functions called by process_order? | What does `Order.force_recalculate_total()` call internally? | `satchmo_store/shop/models.py:881` | `force_recalculate_total()` |
| Q04 | Tax rate? | How is tax rate determined at checkout? | `tax/modules/percent/processor.py` | `config_value('TAX','PERCENT')` |
| Q05 | What happens on cancel_order? | What happens when an order is cancelled? | `satchmo_store/shop/models.py` | `ORDER_STATUS 'Cancelled'`, `add_status()` |
| Q06 | Status code for shipping error? | What order status indicates a blocked/failed order? | `satchmo_store/shop/models.py` | `'Blocked'` in ORDER_STATUS |
| Q07 | Handle negative quantities? | Does the system validate item quantities before reserving? | `product/utils.py` | `items_in_stock`, `NO_STOCK_CHECKOUT` |
| Q08 | Promo codes & discounts? | What fields control discount eligibility and rates? | `product/models.py` | `Discount.code`, `amount`, `percentage` |
| Q09 | Order timestamp generation? | How is the order creation timestamp recorded? | `satchmo_store/shop/models.py` | `time_stamp = models.DateTimeField()` |
| Q10 | Payment gateway retries? (refusal case) | Does Satchmo implement payment retry logic? (expect: not found) | N/A | — |

## Evaluation metric

- **Pass** = correct answer + correct source citation
- **Refuse** = correct refusal when info not in code (Q10)
- **Fail** = wrong answer or hallucinated citation

Target: 10/10 pass rate on provided examples, then run against Satchmo subset.

## Responsible AI note

Key risk: **hallucination** — LLM invents an answer not grounded in the actual code.
Mitigation: answers must include a direct code citation; if no citation found → refuse.
