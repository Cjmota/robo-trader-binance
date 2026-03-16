import pandas as pd
import numpy as np
from src.indicators.vortex import vortex

BUY = "BUY"
SELL = "SELL"
HOLD = None


def getAdvancedTradeStrategy_v3(
    bot=None,
    stock_data: pd.DataFrame = None,
    m7_period: int = 7,
    m200_period: int = 200,
    m50_period: int = 50,
    rsi_period: int = 14,
    slowK_window: int = 14,
    slow_stochastic_smoothing_window: int = 3,
    vortex_window: int = 14,
    verbose: bool = True,
):

    if stock_data is None or len(stock_data) < 50:
        return HOLD

    df = stock_data.copy()
    df.sort_values("open_time", inplace=True)

    # -------------------------
    # Médias móveis

    df["M7"] = df["close_price"].rolling(m7_period).mean()
    df["M50"] = df["close_price"].rolling(m50_period).mean()
    df["M200"] = df["close_price"].rolling(m200_period).mean()

    # -------------------------
    # MACD

    df["EMA12"] = df["close_price"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["close_price"].ewm(span=26, adjust=False).mean()

    df["MACD"] = df["EMA12"] - df["EMA26"]
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    # -------------------------
    # RSI

    delta = df["close_price"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(rsi_period).mean()
    avg_loss = loss.rolling(rsi_period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    df["RSI"] = 100 - (100 / (1 + rs))

    # -------------------------
    # Stochastic

    lowest_low = df["low_price"].rolling(slowK_window).min()
    highest_high = df["high_price"].rolling(slowK_window).max()

    denom = (highest_high - lowest_low).replace(0, np.nan)

    df["fast_K"] = 100 * (df["close_price"] - lowest_low) / denom
    df["SlowS"] = df["fast_K"].rolling(slow_stochastic_smoothing_window).mean()

    # -------------------------
    # Vortex

    df["VIP"] = vortex(df, window=vortex_window, positive=True)
    df["VIM"] = vortex(df, window=vortex_window, positive=False)

    df.dropna(inplace=True)

    if len(df) < 3:
        return HOLD

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    decision = HOLD

    # -------------------------
    # BUY CONDITIONS

    buy_condition = (

        latest["close_price"] > latest["M200"] and
        latest["MACD"] > latest["MACD_signal"] and
        latest["MACD_hist"] > prev["MACD_hist"] and
        latest["SlowS"] < 80 and
        latest["VIP"] > latest["VIM"]

    )

    # -------------------------
    # SELL CONDITIONS

    sell_condition = (

        latest["MACD"] < latest["MACD_signal"] and
        latest["MACD_hist"] < prev["MACD_hist"]

    )

    if buy_condition:
        decision = BUY

    elif sell_condition:
        decision = SELL

    # -------------------------
    # LOG

    if verbose:

        print("-------")
        print("📊 Estratégia: Advanced V3")
        print(f" | Close: {latest['close_price']:.4f}")
        print(f" | MACD: {latest['MACD']:.4f}")
        print(f" | Histogram: {latest['MACD_hist']:.4f}")
        print(f" | RSI: {latest['RSI']:.2f}")
        print(f" | SlowS: {latest['SlowS']:.2f}")
        print(f" | VIP: {latest['VIP']:.3f}")
        print(f" | VIM: {latest['VIM']:.3f}")
        print(f" | Decisão: {decision}")
        print("-------")

    return decision