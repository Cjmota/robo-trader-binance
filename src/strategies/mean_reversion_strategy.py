import pandas as pd
from src.indicators.indicators import Indicators

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


def mean_reversion_strategy(
    bot=None,
    stock_data=None,
    verbose=True,
    **kwargs   # 🔥 ESSENCIAL
):

    if stock_data is None or len(stock_data) < 20:
        return {"action": HOLD, "confidence": 0}

    df = stock_data.copy()
    df = df.rename(columns={"close_price": "close"})

    # RSI
    df["RSI"] = Indicators.getRSI(df, last_only=False)

    last_rsi = df["RSI"].iloc[-1]
    prev_rsi = df["RSI"].iloc[-2]

    rsi_diff = last_rsi - prev_rsi

    decision = HOLD

    # 🔵 COMPRA: sobrevenda + virando pra cima
    if last_rsi < 35 and rsi_diff > 1:
        decision = BUY

    # 🔴 VENDA: sobrecompra + virando pra baixo
    elif last_rsi > 65 and rsi_diff < -1:
        decision = SELL

    confidence = min(abs(rsi_diff) / 10, 1.0)

    print("📊 Mean Reversion")
    print(f"RSI: {last_rsi:.2f} | ΔRSI: {rsi_diff:.2f} | {decision}")

    return {
        "action": decision,
        "confidence": confidence
    }