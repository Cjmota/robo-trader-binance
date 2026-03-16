def multiTimeframeTrend(bot, symbol):

    data_15m = bot.getStockData(symbol, interval="15m")
    data_1h = bot.getStockData(symbol, interval="1h")

    if data_15m is None or data_1h is None:
        return None

    ma_fast_15 = data_15m["close_price"].rolling(7).mean().iloc[-1]
    ma_slow_15 = data_15m["close_price"].rolling(40).mean().iloc[-1]

    ma_fast_1h = data_1h["close_price"].rolling(7).mean().iloc[-1]
    ma_slow_1h = data_1h["close_price"].rolling(40).mean().iloc[-1]

    trend_15 = "UP" if ma_fast_15 > ma_slow_15 else "DOWN"
    trend_1h = "UP" if ma_fast_1h > ma_slow_1h else "DOWN"

    if trend_15 == trend_1h:
        return trend_15

    return "NEUTRAL"