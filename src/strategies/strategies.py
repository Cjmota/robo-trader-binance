def strategy_vortex_rsi(bot, stock_data, verbose=True):

    score = 0
    max_score = 0

    # RSI
    rsi = stock_data["rsi"].iloc[-1]

    if rsi < 30:
        score += 1
    elif rsi > 70:
        score -= 1

    max_score += 1

    # TENDÊNCIA
    ema_fast = stock_data["ema_fast"].iloc[-1]
    ema_slow = stock_data["ema_slow"].iloc[-1]

    if ema_fast > ema_slow:
        score += 1
    else:
        score -= 1

    max_score += 1

    # VOLUME
    volume = stock_data["volume"].iloc[-1]
    avg_volume = stock_data["volume"].rolling(20).mean().iloc[-1]

    if avg_volume != avg_volume:  # NaN
        avg_volume = volume

    if volume > avg_volume:
        score += 0.5

    max_score += 0.5

    # NORMALIZAÇÃO
    final_score = score / max_score
    probability = min(abs(final_score) * 1.5, 1.0)

    # DECISÃO
    if final_score > 0.3:
        signal = "BUY"
    elif final_score < -0.3:
        signal = "SELL"
    else:
        signal = "HOLD"

    return {
        "signal": signal,
        "score": round(final_score, 4),
        "probability": round(probability, 4),
        "regime": "TREND",
        "momentum": abs(final_score) > 0.4,
    }