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

# 🔧 AJUSTE DE PREÇO (NOVO)
def adjust_price(client, symbol, price):

    symbol_info = client.get_symbol_info(symbol)

    price_filter = next(f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER')

    tick_size = float(price_filter['tickSize'])

    precision = int(round(-math.log(tick_size, 10), 0))

    return round(price, precision)

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
    order_buy = None

    print(
        f"[create_order] {_symbol} | {_side} | {_type} | qty={_quantity}"
    )

    # 🔧 PEGAR PREÇO UMA VEZ (OTIMIZAÇÃO)
    ticker = client_binance.get_symbol_ticker(symbol=_symbol)
    market_price = float(ticker['price'])

    # 🔧 AJUSTE DE QUANTIDADE
    _quantity = adjust_quantity(client_binance, _symbol, _quantity)

    if _quantity == 0:
        print("❌ Quantidade inválida")
        return None

    # 🔧 VALIDAR NOTIONAL
    notional = _quantity * market_price

    if notional < 5:
        print(f"❌ Ordem muito pequena: {notional:.2f} USDT")
        return None

    # 🔧 AJUSTAR PREÇOS (SE NECESSÁRIO)
    if _limit_price is not None:
        _limit_price = adjust_price(client_binance, _symbol, _limit_price)

        # 🔧 SLIPPAGE CONTROL
        diff = abs(_limit_price - market_price) / market_price

        volatility = abs(_limit_price - market_price) / market_price
        max_slippage = 0.002 + (volatility * 2)

        if diff > max_slippage:
            print(f"⚠️ Slippage alto: {diff:.4f}")
            return None

    if _stop_price is not None:
        _stop_price = adjust_price(client_binance, _symbol, _stop_price)
        
    # 🔒 evita ordem duplicada muito rápida
    import time

    if hasattr(client_binance, "_last_order_time"):
        if time.time() - client_binance._last_order_time < 2:
            print("⚠️ Ordem muito rápida, ignorando")
            return None

    client_binance._last_order_time = time.time()    
    

    # -----------------------------------------
    # 🚀 EXECUÇÃO COM RETRY

    for i in range(3):
        try:

            ticker = client_binance.get_symbol_ticker(symbol=_symbol)
            market_price = float(ticker['price'])

            if _limit_price is None and _stop_price is None:
                order_buy = client_binance.create_order(
                    symbol=_symbol,
                    side=_side,
                    type=_type,
                    quantity=_quantity,
                )

            elif _limit_price is not None and _stop_price is None:
                order_buy = client_binance.create_order(
                    symbol=_symbol,
                    side=_side,
                    type=_type,
                    timeInForce=_timeInForce,
                    quantity=_quantity,
                    price=_limit_price,
                )

            elif _limit_price is not None and _stop_price is not None:
                order_buy = client_binance.create_order(
                    symbol=_symbol,
                    side=_side,
                    type=_type,
                    timeInForce=_timeInForce,
                    quantity=_quantity,
                    price=_limit_price,
                    stopPrice=_stop_price,
                )

            if order_buy and order_buy.get("status") not in ["FILLED", "PARTIALLY_FILLED"]:
                print(f"⚠️ Ordem não executada: {order_buy.get('status')}")
                return None

            executed_qty = order_buy.get("executedQty", _quantity)

            print(f"✅ Ordem executada (tentativa {i+1})")
            print(f"📊 EXECUTADO: {_side} {_symbol} | qty={executed_qty}")

            break

        except Exception as e:
            print(f"⚠️ Tentativa {i+1} falhou: {e}")

            if "insufficient" in str(e).lower():
                print("💸 Saldo insuficiente")
                return None

            order_buy = None

    # -----------------------------------------
    if order_buy is None:
        print("❌ Falha total na execução")

    return order_buy