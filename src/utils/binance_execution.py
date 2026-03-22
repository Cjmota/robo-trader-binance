import math
import time

# 🔥 CACHE (evita ficar consultando API toda hora)
_SYMBOL_FILTER_CACHE = {}
_CACHE_TTL = 300  # 5 minutos


def _get_symbol_info(client, symbol):
    now = time.time()

    if symbol in _SYMBOL_FILTER_CACHE:
        data, timestamp = _SYMBOL_FILTER_CACHE[symbol]
        if now - timestamp < _CACHE_TTL:
            return data

    info = client.get_symbol_info(symbol)
    _SYMBOL_FILTER_CACHE[symbol] = (info, now)
    return info


def get_all_filters(client, symbol):
    info = _get_symbol_info(client, symbol)

    filters = {
        "LOT_SIZE": None,
        "MIN_NOTIONAL": None,
        "PRICE_FILTER": None
    }

    for f in info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            filters["LOT_SIZE"] = {
                "minQty": float(f["minQty"]),
                "maxQty": float(f["maxQty"]),
                "stepSize": float(f["stepSize"])
            }

        elif f["filterType"] == "MIN_NOTIONAL":
            filters["MIN_NOTIONAL"] = float(f["minNotional"])

        elif f["filterType"] == "PRICE_FILTER":
            filters["PRICE_FILTER"] = {
                "tickSize": float(f["tickSize"])
            }

    return filters


# -----------------------------------------
# 🔧 AJUSTES

def adjust_quantity(qty, step):
    def adjust_quantity(qty, step):
        if step <= 0:
            return qty

        precision = int(round(-math.log(step, 10), 0))
        return float(round(qty - (qty % step), precision))

def adjust_price(price, tick):
    precision = int(round(-math.log(tick, 10), 0))
    return float(round(price - (price % tick), precision))


# -----------------------------------------
# 🧠 VALIDAÇÃO COMPLETA

def validate_order(client, symbol, qty, price):

    if not price or price <= 0:
        return 0, price, "Invalid price"

    filters = get_all_filters(client, symbol)

    lot = filters.get("LOT_SIZE")
    min_notional = filters.get("MIN_NOTIONAL") or 0
    price_filter = filters.get("PRICE_FILTER")

    if not lot:
        return 0, price, "LOT_SIZE missing"

    # 🔧 ajusta quantidade
    qty = adjust_quantity(qty, lot["stepSize"])

    if qty < lot["minQty"]:
        return 0, price, "Qty < minQty"

    # 🔧 ajusta preço
    if price_filter:
        price = adjust_price(price, price_filter["tickSize"])

    # 🔧 valida valor mínimo
    notional = qty * price

    if notional < min_notional:
        return 0, price, f"Notional < {min_notional}"

    return qty, price, None