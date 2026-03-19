import pandas as pd
from src.indicators.indicators import Indicators

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


def mean_reversion_strategy(
    bot=None,
    stock_data=None,
    verbose=True,
    **kwargs
):
    import pandas as pd
    from src.indicators.indicators import Indicators

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

    if stock_data is None or len(stock_data) < 20:
        return {"action": HOLD, "confidence": 0}

    df = stock_data.rename(columns={"close_price": "close"}).copy()

    df["RSI"] = Indicators.getRSI(df, last_only=False)

    rsi = df["RSI"].iloc[-1]
    prev_rsi = df["RSI"].iloc[-2]

    rsi_diff = rsi - prev_rsi

    decision = HOLD

    # -----------------------------------------
    # 🎯 LÓGICA PROFISSIONAL MEAN REVERSION

    # 🔻 SOBRECOMPRA → VENDA
    if rsi > 65 and rsi_diff < 0:
        decision = SELL

    # 🔺 SOBREVENDA → COMPRA
    elif rsi < 35 and rsi_diff > 0:
        decision = BUY

    # -----------------------------------------
    # 🔥 FORÇA = CONFIANÇA
    confidence = min(abs(rsi_diff) / 10, 1)

    # -----------------------------------------
    if verbose:
        print("📊 Mean Reversion")
        print(f"RSI: {rsi:.2f} | ΔRSI: {rsi_diff:.2f} | {decision}")

    return {
        "action": decision,
        "confidence": confidence,
        "score": 0.3 if decision == BUY else -0.3 if decision == SELL else 0,
        "momentum": abs(rsi_diff) > 1,
        "volume_spike": abs(rsi_diff) > 2,
        "orderflow": "BUY" if decision == BUY else "SELL" if decision == SELL else "NEUTRAL"
    }