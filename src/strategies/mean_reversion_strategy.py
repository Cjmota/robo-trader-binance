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
    
    # -----------------------------------------
    # 📊 BOLLINGER BANDS + Z-SCORE

    window = 20

    df["ma"] = df["close"].rolling(window).mean()
    df["std"] = df["close"].rolling(window).std()

    df["upper"] = df["ma"] + (2 * df["std"])
    df["lower"] = df["ma"] - (2 * df["std"])

    price = df["close"].iloc[-1]
    upper = df["upper"].iloc[-1]
    lower = df["lower"].iloc[-1]

    # evita erro de divisão por zero
    if df["std"].iloc[-1] == 0 or pd.isna(df["std"].iloc[-1]):
        return {"action": HOLD, "confidence": 0}

    zscore = (price - df["ma"].iloc[-1]) / df["std"].iloc[-1]

    rsi = df["RSI"].iloc[-1]
    prev_rsi = df["RSI"].iloc[-2]
    rsi_diff = rsi - prev_rsi

    decision = HOLD

    # -----------------------------------------
    # 🔥 LÓGICA COM Z-SCORE + RSI

    # 🔻 VENDA (TOPO)

    if zscore > 2:
        decision = SELL

    elif zscore > 1.5 and rsi > 65:
        decision = SELL

    # 🔺 COMPRA (FUNDO)

    elif zscore < -2:
        decision = BUY

    elif zscore < -1.5 and rsi < 35:
        decision = BUY
        
    # -----------------------------------------
    # 📈 TREND FILTER (DEPOIS DA DECISÃO)

    ema50 = df["close"].rolling(50).mean().iloc[-1]
    price = df["close"].iloc[-1]

    trend = "UP" if price > ema50 else "DOWN"

    # 🔥 permite extremos mesmo contra tendência

    if trend == "UP" and decision == SELL and zscore < 2:
        decision = HOLD

    if trend == "DOWN" and decision == BUY and zscore > -2:
        decision = HOLD

    # -----------------------------------------
    # 🔥 CONFIANÇA INTELIGENTE

    distance = abs(rsi - 50)
    confidence = min((distance / 50) + (abs(rsi_diff) / 10), 1)

    # -----------------------------------------
    if verbose:
        # 🔥 permite extremos mesmo contra tendência
        print("📊 Mean Reversion BB")
        print(f"RSI: {rsi:.2f} | ΔRSI: {rsi_diff:.2f}")
        print(f"ZScore: {zscore:.2f}")
        print(f"Upper: {upper:.2f} | Lower: {lower:.2f}")
        print(f"📈 Trend: {trend} | Decision: {decision}")

    return {
        "action": decision,
        "confidence": confidence,
        "score": 0.4 if decision == BUY else -0.4 if decision == SELL else 0,
        "momentum": abs(rsi_diff) > 1,
        "volume_spike": abs(rsi_diff) > 2,
        "orderflow": "BUY" if decision == BUY else "SELL" if decision == SELL else "NEUTRAL"
    }