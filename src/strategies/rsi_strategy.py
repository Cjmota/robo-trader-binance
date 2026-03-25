import pandas as pd
from src.indicators.indicators import Indicators

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


def getRsiTradeStrategy(
    bot=None,
    stock_data: pd.DataFrame = None,
    low: int = 30,
    high: int = 60,
    verbose: bool = True
):

    if stock_data is None or len(stock_data) < 20:
        return {"action": HOLD, "confidence": 0}

    stock_data = stock_data.copy()

    # 🔥 garante coluna close
    if "close" not in stock_data.columns:
        if "close_price" in stock_data.columns:
            stock_data["close"] = stock_data["close_price"]
        else:
            return {"action": HOLD, "confidence": 0}

    # 🔥 RSI SEGURO
    rsi_data = Indicators.getRSI(stock_data, last_only=False)

    if isinstance(rsi_data, pd.DataFrame):
        if "rsi" in rsi_data.columns:
            rsi_series = rsi_data["rsi"]
        else:
            rsi_series = rsi_data.iloc[:, 0]
    else:
        rsi_series = pd.Series(rsi_data, index=stock_data.index)

    rsi_series = rsi_series.astype(float)
    stock_data["RSI"] = rsi_series

    # 🔥 valores seguros
    last_rsi = float(rsi_series.iloc[-1])
    prev_rsi = float(rsi_series.iloc[-2])

    rsi_diff = last_rsi - prev_rsi

    confidence = min(abs(rsi_diff) / 10, 1.0)

    ema_fast = stock_data["close"].ewm(span=9).mean().iloc[-1]
    ema_slow = stock_data["close"].ewm(span=21).mean().iloc[-1]

    trend_up = ema_fast > ema_slow
    trend_down = ema_fast < ema_slow

    if abs(rsi_diff) < 2:
        return {"action": HOLD, "confidence": 0}

    if last_rsi > 52 and rsi_diff > 2 and trend_up:
        decision = BUY

    elif last_rsi < 48 and rsi_diff < -2 and trend_down:
        decision = SELL

    else:
        decision = HOLD

    if verbose:
        print("📊 RSI:", last_rsi, "| diff:", rsi_diff, "| decision:", decision)

    return {
        "action": decision,
        "confidence": confidence
    }    
    