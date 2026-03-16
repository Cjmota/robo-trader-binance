import pandas as pd

TREND = "TREND"
RANGE = "RANGE"
EXPLOSIVE = "EXPLOSIVE"


def detectMarketRegime(stock_data: pd.DataFrame):

    if stock_data is None or len(stock_data) < 50:
        return RANGE

    close = stock_data["close_price"]

    # -------------------------
    # Volatilidade

    volatility = close.pct_change().rolling(20).std().iloc[-1]

    if pd.isna(volatility):
        return RANGE

    # -------------------------
    # Médias móveis

    ma_fast = close.rolling(7).mean().iloc[-1]
    ma_slow = close.rolling(40).mean().iloc[-1]

    if pd.isna(ma_fast) or pd.isna(ma_slow) or ma_slow == 0:
        return RANGE

    trend_strength = abs(ma_fast - ma_slow) / ma_slow

    # -------------------------
    # Momentum

    momentum = (close.iloc[-1] - close.iloc[-4]) / close.iloc[-4]

    # -------------------------
    # Regime

    if volatility > 0.02 and abs(momentum) > 0.01:
        return EXPLOSIVE

    if trend_strength > 0.01:
        return TREND

    return RANGE