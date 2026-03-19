import logging
import math


def adjust_quantity(client, symbol, quantity):

    symbol_info = client.get_symbol_info(symbol)

    lot_filter = next(f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE')

    step_size = float(lot_filter['stepSize'])
    min_qty = float(lot_filter['minQty'])

    precision = int(round(-math.log(step_size, 10), 0))

    quantity = round(quantity, precision)

    if quantity < min_qty:
        print(f"❌ Quantidade menor que mínimo: {min_qty}")
        return 0

    return quantity

def create_order(
    client_binance,
    _symbol,
    _side,
    _type,
    _quantity,
    _timeInForce=None,
    _limit_price=None,
    _stop_price=None,
):
    ordemExecute = 0
    order_buy = None  # 🔧 evita erro

    try:
        print(
            f"[create_order] _symbol: '{_symbol}', _side: '{_side}', _type: '{_type}', _quantity: '{_quantity}'"
        )

        # 🔧 AJUSTE DE QUANTIDADE
        _quantity = adjust_quantity(client_binance, _symbol, _quantity)

        if _quantity == 0:
            print("❌ Ordem cancelada: quantidade inválida")
            return None

        # 🔧 VALIDAR NOTIONAL (ANTES DA ORDEM)
        price = float(client_binance.get_symbol_ticker(symbol=_symbol)['price'])
        notional = _quantity * price

        if notional < 5:
            print(f"❌ Ordem muito pequena: {notional:.2f} USDT")
            return None

        # -----------------------------------------
        # 🚀 EXECUÇÃO

        if _limit_price is None and _stop_price is None:
            ordemExecute = 1
            order_buy = client_binance.create_order(
                symbol=_symbol,
                side=_side,
                type=_type,
                quantity=_quantity,
            )

        elif _limit_price is not None and _stop_price is None:
            ordemExecute = 2
            order_buy = client_binance.create_order(
                symbol=_symbol,
                side=_side,
                type=_type,
                timeInForce=_timeInForce,
                quantity=_quantity,
                price=round(_limit_price, 2),
            )

        elif _limit_price is not None and _stop_price is not None:
            ordemExecute = 3
            order_buy = client_binance.create_order(
                symbol=_symbol,
                side=_side,
                type=_type,
                timeInForce=_timeInForce,
                quantity=_quantity,
                price=round(_limit_price, 2),
                stopPrice=round(_stop_price, 2),
            )

    except Exception as e:
        print(f"[ERROR] Ordem falhou: {e}")
        logging.error(f"[ERROR] Ordem falhou: {e}")

    return order_buy
