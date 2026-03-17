import pandas as pd
from src.indicators import Indicators

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


def vortex_rsi_volume_strategy(bot=None, stock_data=None, verbose=True):

    if stock_data is None or len(stock_data) < 50:
        return {"signal": HOLD}

    df = stock_data.copy()

    # -------------------------
    # INDICADORES

    df["VI+"] = Indicators.getVortex(df, window=14, positive=True)
    df["VI-"] = Indicators.getVortex(df, window=14, positive=False)
    df["RSI"] = Indicators.getRSI(df, window=14)

    df["VOL_MEAN"] = df["volume"].rolling(20).mean()

    df.dropna(inplace=True)

    if len(df) < 3:
        return {"signal": HOLD}

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # -------------------------
    # 📊 VALORES

    vi_diff = latest["VI+"] - latest["VI-"]
    rsi = latest["RSI"]
    volume_ok = latest["volume"] > latest["VOL_MEAN"]

    # -------------------------
    # 🧠 SCORE

    score = 0

    # tendência (peso forte)
    if vi_diff > 0:
        score += 1
    else:
        score -= 1

    # RSI (timing)
    if rsi < 35:
        score += 0.5
    elif rsi > 65:
        score -= 0.5

    # volume (confirmação)
    if volume_ok:
        score += 0.3 if score > 0 else -0.3

    # -------------------------
    # NORMALIZAÇÃO

    max_score = 1.8
    final_score = score / max_score
    probability = abs(final_score)

    # -------------------------
    # DECISÃO

    if final_score > 0.25:
        signal = BUY
    elif final_score < -0.25:
        signal = SELL
    else:
        signal = HOLD

    # -------------------------
    # LOG

    if verbose:
        print("📊 Vortex+RSI+Volume")
        print(f"Score: {final_score:.3f} | Prob: {probability:.3f} | RSI: {rsi:.1f}")

    return {
        "signal": signal,
        "score": round(final_score, 4),
        "probability": round(probability, 4),
        "regime": "TREND",
        "volume_spike": volume_ok,
        "momentum": abs(final_score) > 0.5,
    }