import pandas as pd

TREND = "TREND"
RANGE = "RANGE"
EXPLOSIVE = "EXPLOSIVE"


def detectMarketRegime(stock_data: pd.DataFrame):

    close = stock_data["close_price"]

    volatility = close.pct_change().rolling(20).std().iloc[-1]

    ma_fast = close.rolling(7).mean().iloc[-1]
    ma_slow = close.rolling(40).mean().iloc[-1]

    trend_strength = abs(ma_fast - ma_slow) / ma_slow

    if volatility > 0.02:
        return EXPLOSIVE

    if trend_strength > 0.01:
        return TREND

    return RANGE