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
    
    
    rsi_data = Indicators.getRSI(df, last_only=False)

    if isinstance(rsi_data, pd.DataFrame):
        if "rsi" in rsi_data.columns:
            df["RSI"] = rsi_data["rsi"]
        else:
            df["RSI"] = rsi_data.iloc[:, 0]
    else:
        df["RSI"] = rsi_data
    
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
    
    # -----------------------------------------
    # 🚀 VOLATILIDADE DINÂMICA (AUTO AJUSTE)

    volatility = df["std"].iloc[-1]
    avg_volatility = df["std"].rolling(50).mean().iloc[-1]

    if avg_volatility == 0 or pd.isna(avg_volatility):
        vol_factor = 1
    else:
        vol_factor = volatility / avg_volatility

    # 🔥 threshold adaptativo por mercado
    if volatility < avg_volatility:
        base_threshold = 0.6   # mercado calmo → mais entradas
    else:
        base_threshold = 0.9   # mercado forte → mais seletivo

    dynamic_threshold = base_threshold * (1 + (vol_factor - 1))

    # proteção mínima
    dynamic_threshold = max(0.8, min(dynamic_threshold, 2.0))

    print(f"📊 VolFactor: {vol_factor:.2f} | Threshold: {dynamic_threshold:.2f}")

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

    signal_strength = abs(zscore)

    # -----------------------------------------
    # 🔥 LÓGICA DINÂMICA (AUTO AJUSTE)

    strong_threshold = dynamic_threshold + 0.5

    # 🔻 VENDA
    if zscore > strong_threshold and rsi > 60:
        decision = SELL

    elif zscore > dynamic_threshold and rsi > 55:
        decision = SELL

    # 🔺 COMPRA
    elif zscore < -strong_threshold and rsi < 45:
        decision = BUY

    elif zscore < -dynamic_threshold:
        decision = BUY
        
    # 🚀 fallback leve (evita HOLD infinito)
    if decision == HOLD:

        if zscore > dynamic_threshold * 0.4:
            decision = SELL

        elif zscore < -dynamic_threshold * 0.4:
            decision = BUY
            
    # -----------------------------------------
    # 📈 TREND FILTER (DEPOIS DA DECISÃO)

    ema50 = df["close"].rolling(50).mean().iloc[-1]
    price = df["close"].iloc[-1]

    trend = "UP" if price > ema50 else "DOWN"
    
    # -----------------------------------------
    # 🔥 SCORE PROFISSIONAL (SUBSTITUI SCORE FIXO)

    score = 0

    # ZSCORE (principal driver)
    score += zscore * 0.6

    # RSI (força)
    score += ((rsi - 50) / 50) * 0.3

    # MOMENTUM
    if abs(rsi_diff) > 1:
        score += 0.2 if rsi_diff > 0 else -0.2

    # TREND BOOST
    if trend == "UP":
        score += 0.1
    else:
        score -= 0.1

    # LIMITA SCORE
    score = max(-1, min(1, score))

    # 🔥 permite extremos mesmo contra tendência

    # 🔥 só bloqueia se sinal MUITO fraco
    if decision == SELL and trend == "UP" and signal_strength < 1.2:
        decision = HOLD

    if decision == BUY and trend == "DOWN" and signal_strength < 1.2:
        decision = HOLD

    # -----------------------------------------
    # 🔥 CONFIANÇA INTELIGENTE

    distance = abs(rsi - 50)
    confidence = min(
        (distance / 40) + (abs(zscore) / 2) + (abs(rsi_diff) / 8),
        1
    )

    # -----------------------------------------
    if verbose:
        # 🔥 permite extremos mesmo contra tendência
        print("📊 Mean Reversion BB")
        print(f"RSI: {rsi:.2f} | ΔRSI: {rsi_diff:.2f}")
        print(f"ZScore: {zscore:.2f}")
        print(f"Upper: {upper:.2f} | Lower: {lower:.2f}")
        print(f"📈 Trend: {trend} | Decision: {decision}")

    # 🚀 MODO SPOT (ESSENCIAL)
    if decision == SELL and not getattr(bot, "position_open", False):

        if zscore < -dynamic_threshold * 0.7:
            decision = BUY

            print("💡 Zona de topo → aguardando pullback")

            # 🔥 NOVA LÓGICA INTELIGENTE
            if rsi_diff < -0.5:
                print("🔥 Pullback detectado → entrando BUY antecipado")
                decision = BUY
            else:
                decision = HOLD
        
    if decision == HOLD:
        if zscore < -dynamic_threshold * 0.5 and rsi < 50:
            print("🔥 Entrada antecipada BUY (controlada)")
            decision = BUY

    return {
        "signal": decision,
        "probability": confidence,
        "score": score,
        "momentum": abs(rsi_diff) > 1,
        "volume_spike": df["close"].pct_change().abs().iloc[-1] > 0.004,
        "orderflow": "BUY" if decision == BUY else "SELL" if decision == SELL else "NEUTRAL"
    }