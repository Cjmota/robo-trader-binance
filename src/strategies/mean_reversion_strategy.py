import pandas as pd
from src.indicators.indicators import Indicators

def mean_reversion_strategy(
    bot=None,
    stock_data=None,
    verbose=True,
    **kwargs
):

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

    if stock_data is None or len(stock_data) < 50:
        return {"action": HOLD, "confidence": 0}

    df = stock_data.rename(columns={"close_price": "close"}).copy()

    from src.indicators.indicators import Indicators
    df["RSI"] = Indicators.getRSI(df, last_only=False)

    rsi = df["RSI"].iloc[-1]
    prev_rsi = df["RSI"].iloc[-2]
    rsi_diff = rsi - prev_rsi

    decision = HOLD

    # -----------------------------------------
    # 🎯 LÓGICA PRINCIPAL (SEM DUPLICAÇÃO)

    if rsi > 72:
        decision = SELL

    elif rsi > 65 and rsi_diff < 0:
        decision = SELL

    elif rsi < 28:
        decision = BUY

    elif rsi < 35 and rsi_diff > 0:
        decision = BUY

    # -----------------------------------------
    # 📈 TREND FILTER (DEPOIS DA DECISÃO)

    ema50 = df["close"].rolling(50).mean().iloc[-1]
    price = df["close"].iloc[-1]

    trend = "UP" if price > ema50 else "DOWN"

    if trend == "UP" and decision == SELL:
        decision = HOLD

    if trend == "DOWN" and decision == BUY:
        decision = HOLD

    # -----------------------------------------
    # 🔥 CONFIANÇA INTELIGENTE

    distance = abs(rsi - 50)
    confidence = min((distance / 50) + (abs(rsi_diff) / 10), 1)

    # -----------------------------------------
    if verbose:
        print("📊 Mean Reversion PRO CLEAN")
        print(f"RSI: {rsi:.2f} | ΔRSI: {rsi_diff:.2f} | Dist: {distance:.2f}")
        print(f"📈 Trend: {trend} | Decision: {decision}")

    return {
        "action": decision,
        "confidence": confidence,
        "score": 0.4 if decision == BUY else -0.4 if decision == SELL else 0,
        "momentum": abs(rsi_diff) > 1,
        "volume_spike": abs(rsi_diff) > 2,
        "orderflow": "BUY" if decision == BUY else "SELL" if decision == SELL else "NEUTRAL"
    }