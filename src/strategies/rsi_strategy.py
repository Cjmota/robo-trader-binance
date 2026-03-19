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
        return HOLD

    stock_data = stock_data.copy()

    # -------------------------
    # RSI

    stock_data = stock_data.copy()

    # 🔧 padroniza nome
    stock_data = stock_data.rename(columns={"close_price": "close"})

    # RSI
    stock_data["RSI"] = Indicators.getRSI(
        stock_data,
        last_only=False
    )

    rsi_series = stock_data["RSI"]

    last_rsi = rsi_series.iloc[-1]
    prev_rsi = rsi_series.iloc[-2]

    # -------------------------
    # identificar picos e vales

    peaks = stock_data[rsi_series > high].index
    valleys = stock_data[rsi_series < low].index

    last_peak = peaks[-1] if len(peaks) > 0 else None
    last_valley = valleys[-1] if len(valleys) > 0 else None

    decision = HOLD

    # -------------------------
    # -------------------------
    # DEBUG

    if verbose:
        print("DEBUG RSI CROSS:", prev_rsi, "→", last_rsi)

    # -------------------------
    # -------------------------
    # -------------------------
    # 🔥 LÓGICA PROFISSIONAL (TREND + MOMENTUM)

    # força do movimento
    rsi_diff = last_rsi - prev_rsi

    # -------------------------
    
    # 🔥 FILTRO DE TENDÊNCIA (EMA)
    ema_fast = stock_data["close"].ewm(span=9).mean().iloc[-1]
    ema_slow = stock_data["close"].ewm(span=21).mean().iloc[-1]

    trend_up = ema_fast > ema_slow
    trend_down = ema_fast < ema_slow

    # 🔴 FILTRO DE QUALIDADE
    if abs(rsi_diff) < 2:
        return {"action": HOLD, "confidence": 0}

    # BUY → mercado ganhando força
    if last_rsi > 52 and rsi_diff > 2 and trend_up:
        decision = BUY

    # -------------------------
    # SELL → mercado perdendo força

    elif last_rsi < 48 and rsi_diff < -2 and trend_down:
        decision = SELL

    else:
        decision = HOLD
    # -------------------------
    # Log

    rsi_diff = last_rsi - prev_rsi

    if verbose:
        
        print("DEBUG RSI CROSS:", prev_rsi, "→", last_rsi)
        print(f" | Força RSI: {rsi_diff:.2f}")

        print("-------")
        print("📊 Estratégia: RSI")
        print(f" | RSI atual: {last_rsi:.2f}")
        print(f" | RSI anterior: {prev_rsi:.2f}")
        print(f" | Último vale: {last_valley}")
        print(f" | Último pico: {last_peak}")
        print(f" | Decisão: {decision}")
        print("-------")  
                
        # 🔥 converter força em probabilidade
        confidence = min(abs(rsi_diff) / 10, 1.0)          
    
    return {
    "action": decision,
    "confidence": confidence
    }
    
    