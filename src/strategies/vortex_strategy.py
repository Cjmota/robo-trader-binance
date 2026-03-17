import pandas as pd
from src.indicators.vortex import vortex
from src.indicators.rsi import rsi

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


import pandas as pd
from src.indicators.vortex import vortex
from src.indicators.rsi import rsi

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


def vortex_rsi_volume_strategy(bot=None, stock_data=None, verbose=True):

    if stock_data is None or len(stock_data) < 50:
        return {"signal": HOLD}

    df = stock_data.copy()

    # -------------------------
    # INDICADORES

    df["VI+"] = vortex(df, window=14, positive=True)
    df["VI-"] = vortex(df, window=14, positive=False)

    df["RSI"] = rsi(df["close_price"], window=14, last_only=False)

    df["VOL_MEAN"] = df["volume"].rolling(20).mean()

    df.dropna(inplace=True)

    if len(df) < 3:
        return {"signal": HOLD}

    latest = df.iloc[-1]

    # -------------------------
    # 📊 VALORES

    vi_diff = latest["VI+"] - latest["VI-"]
    rsi_val = latest["RSI"]
    volume_ok = latest["volume"] > latest["VOL_MEAN"]

    # -------------------------
    # 🧠 SCORE

    score = 0

    if vi_diff > 0:
        score += 1
    else:
        score -= 1

    if rsi_val < 35:
        score += 0.5
    elif rsi_val > 65:
        score -= 0.5

    if volume_ok:
        score += 0.3 if score > 0 else -0.3

    final_score = score / 1.8
    probability = abs(final_score)

    # -------------------------
    # 🎯 DECISÃO

    if final_score > 0.25:
        signal = BUY
    elif final_score < -0.25:
        signal = SELL
    else:
        signal = HOLD

    if verbose:
        print(f"📊 Score: {final_score:.3f} | Prob: {probability:.3f}")

    return {
        "signal": signal,
        "score": round(final_score, 4),
        "probability": round(probability, 4),
        "regime": "TREND",
        "volume_spike": volume_ok,
        "momentum": abs(final_score) > 0.5,
    }