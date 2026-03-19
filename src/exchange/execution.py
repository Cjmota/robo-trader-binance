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

    try:
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

            if diff > 0.002:
                print(f"⚠️ Slippage alto: {diff:.4f}")
                return None

        if _stop_price is not None:
            _stop_price = adjust_price(client_binance, _symbol, _stop_price)

        # -----------------------------------------
        # 🚀 EXECUÇÃO COM RETRY

        for i in range(3):
            try:
                # MARKET
                if _limit_price is None and _stop_price is None:
                    ordemExecute = 1
                    order_buy = client_binance.create_order(
                        symbol=_symbol,
                        side=_side,
                        type=_type,
                        quantity=_quantity,
                    )

                # LIMIT
                elif _limit_price is not None and _stop_price is None:
                    ordemExecute = 2
                    order_buy = client_binance.create_order(
                        symbol=_symbol,
                        side=_side,
                        type=_type,
                        timeInForce=_timeInForce,
                        quantity=_quantity,
                        price=_limit_price,
                    )

                # STOP
                elif _limit_price is not None and _stop_price is not None:
                    ordemExecute = 3
                    order_buy = client_binance.create_order(
                        symbol=_symbol,
                        side=_side,
                        type=_type,
                        timeInForce=_timeInForce,
                        quantity=_quantity,
                        price=_limit_price,
                        stopPrice=_stop_price,
                    )

                print(f"✅ Ordem executada (tentativa {i+1})")
                break

            except Exception as e:
                print(f"⚠️ Tentativa {i+1} falhou: {e}")
                order_buy = None

    except Exception as e:
        print(f"[ERROR] Ordem falhou: {e}")
        logging.error(f"[ERROR] Ordem falhou: {e}")

    return order_buy