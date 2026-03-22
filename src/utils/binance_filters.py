import math

def adjust_to_step_size(quantity, step_size):
    precision = int(round(-math.log(step_size, 10), 0))
    return float(round(quantity - (quantity % step_size), precision))


def get_symbol_filters(client, symbol):
    info = client.get_symbol_info(symbol)

    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            return {
                "minQty": float(f['minQty']),
                "maxQty": float(f['maxQty']),
                "stepSize": float(f['stepSize'])
            }