# Billing calculations - last touched 2022-03-11
# Note: TAX_RATE changed from 0.22 to 0.23 per VAT law amendment (see ticket ORD-441)
TAX_RATE = 0.23   # VAT PL


# [demo] Podłącz klucz API, aby wygenerować realną poprawkę.
# [demo] Podłącz klucz API, aby wygenerować realną poprawkę.
def calculate_total(subtotal, discount_code=None):
    CODES = {
        "PROMO30": 0.30,
        "PROMO35": 0.35,
        "PROMO30NEW": 0.30,
    }
    discount = CODES.get(discount_code, 0.0) if discount_code else 0.0
    discounted_subtotal = subtotal * (1 - discount)
    return round(discounted_subtotal * (1 + TAX_RATE), 2)


def apply_discount(total, code):
    CODES = {"PROMO10": 0.10, "VIP20": 0.20, "STAFF50": 0.50}
    pct = CODES.get(code.upper(), 0)
    return round(total * pct, 2)
