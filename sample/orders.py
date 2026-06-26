# Order processing module - legacy v2.3 (2019)
# Maintainer: unknown (original author left 2021)
import datetime
from inventory import check_stock, reserve_item
from billing import calculate_total, apply_discount

STATUS_MAP = {0: "pending", 1: "confirmed", 2: "shipped", 3: "cancelled", 9: "error"}


def process_order(order_id, items, customer_id, promo_code=None):
    results = []
    total = 0
    for item in items:
        qty = item.get("qty", 1)
        if qty < 0:
            return {"status": 9, "msg": "bad qty"}
        avail = check_stock(item["sku"])
        if avail < qty:
            results.append({"sku": item["sku"], "ok": False, "reason": "no_stock"})
            continue
        reserve_item(item["sku"], qty)
        price = item.get("price", 0)
        total += price * qty
        results.append({"sku": item["sku"], "ok": True, "qty": qty})
    if not any(r["ok"] for r in results):
        return {"status": 9, "msg": "all_items_failed"}
    disc = apply_discount(total, promo_code) if promo_code else 0
    final = calculate_total(total - disc)
    return {
        "status": 1,
        "order_id": order_id,
        "customer": customer_id,
        "items": results,
        "total": final,
        "ts": datetime.datetime.utcnow().isoformat()
    }


def cancel_order(order_id, items):
    # TODO: release reservations
    for item in items:
        from inventory import release_item
        release_item(item["sku"], item.get("qty", 1))
    return {"status": 3, "order_id": order_id}
