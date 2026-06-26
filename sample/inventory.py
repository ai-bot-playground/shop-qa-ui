# Inventory / stock management - legacy v1.8 (2018)
# WARNING: STOCK is in-memory only. No DB persistence. Resets on process restart.

STOCK = {
    "SKU-001": 100,
    "SKU-002": 45,
    "SKU-003": 0,
    "SKU-004": 200,
    "SKU-005": 12,
}


def check_stock(sku):
    return STOCK.get(sku, 0)


def reserve_item(sku, qty):
    if STOCK.get(sku, 0) < qty:
        raise ValueError(f"Cannot reserve {qty} of {sku}: only {STOCK.get(sku, 0)} available")
    STOCK[sku] -= qty


def release_item(sku, qty):
    # called by cancel_order to undo a reservation
    STOCK[sku] = STOCK.get(sku, 0) + qty
