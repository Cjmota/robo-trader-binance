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

    df = stock_data.copy()

    # 🔥 garante coluna close
    if "close" not in df.columns:

        if "close_price" in df.columns:
            df["close"] = df["close_price"]

        elif "Close" in df.columns:
            df["close"] = df["Close"]

        else:
            print("❌ ERRO: coluna CLOSE não encontrada")
            print(df.columns)
            return {"action": HOLD, "confidence": 0}

    from src.indicators.indicators import Indicators
    df["RSI"] = Indicators.getRSI(df, last_only=False)
    
    # -----------------------------------------
    # 📊 BOLLINGER BANDS + Z-SCORE

    if df["close"].nunique() <= 1:
        print("❌ CLOSE sem variação (std = 0)")
        return {"action": HOLD, "confidence": 0}

    if len(df) < 50:
        print("❌ Poucos dados")
        return {"action": HOLD, "confidence": 0}

    window = 20

    df["ma"] = df["close"].rolling(window).mean()
    df["std"] = df["close"].rolling(window).std()

    df["upper"] = df["ma"] + (2 * df["std"])
    df["lower"] = df["ma"] - (2 * df["std"])
    
    print("🔎 CLOSE:")
    print(df["close"].tail(10))

    print("🔎 STD:")
    print(df["std"].tail(10))

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

    signal_strength = 0

    # 🔻 VENDA
    if zscore > 1.5 and rsi > 60:
        decision = SELL
        signal_strength = 2

    elif zscore > 1.2:
        decision = SELL
        signal_strength = 1


    # 🔺 COMPRA
    elif zscore < -1.5 and rsi < 40:
        decision = BUY
        signal_strength = 2

    elif zscore < -1.2:
        decision = BUY
        signal_strength = 1
            
    # -----------------------------------------
    # 📈 TREND FILTER (DEPOIS DA DECISÃO)

    ema50 = df["close"].rolling(50).mean().iloc[-1]
    price = df["close"].iloc[-1]

    trend = "UP" if price > ema50 else "DOWN"

    # 🔥 permite extremos mesmo contra tendência

    # 🔥 só bloqueia se sinal MUITO fraco
    if decision == SELL and trend == "UP" and signal_strength == 1:
        decision = HOLD

    if decision == BUY and trend == "DOWN" and signal_strength == 1:
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