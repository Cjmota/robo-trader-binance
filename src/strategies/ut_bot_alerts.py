import numpy as np
import pandas as pd

BUY = "BUY"
SELL = "SELL"
HOLD = None


def calculate_atr(high, low, close, period=10):

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period, min_periods=period).mean()

    return atr


def utBotAlerts(
    bot=None,
    stock_data: pd.DataFrame = None,
    atr_period=10,
    atr_multiplier=2,
    verbose=True
):

    if stock_data is None or len(stock_data) < atr_period + 5:
        return HOLD

    high = stock_data["high_price"]
    low = stock_data["low_price"]
    close = stock_data["close_price"]

    atr = calculate_atr(high, low, close, atr_period)

    trailing_stop = pd.Series(index=close.index, dtype=float)

    trailing_stop.iloc[0] = close.iloc[0]

    for i in range(1, len(close)):

        if pd.isna(atr.iloc[i]):
            trailing_stop.iloc[i] = trailing_stop.iloc[i - 1]
            continue

        if close.iloc[i] > trailing_stop.iloc[i - 1]:

            trailing_stop.iloc[i] = max(
                trailing_stop.iloc[i - 1],
                close.iloc[i] - atr_multiplier * atr.iloc[i]
            )

        else:

            trailing_stop.iloc[i] = min(
                trailing_stop.iloc[i - 1],
                close.iloc[i] + atr_multiplier * atr.iloc[i]
            )

    pos = np.zeros(len(close))

    for i in range(1, len(close)):

        if close.iloc[i - 1] < trailing_stop.iloc[i - 1] and close.iloc[i] > trailing_stop.iloc[i]:

            pos[i] = 1

        elif close.iloc[i - 1] > trailing_stop.iloc[i - 1] and close.iloc[i] < trailing_stop.iloc[i]:

            pos[i] = -1

        else:

            pos[i] = pos[i - 1]

    decision = HOLD

    if pos[-1] == 1:
        decision = BUY

    elif pos[-1] == -1:
        decision = SELL

    if verbose:

        print("-------")
        print("📊 Estratégia: UT Bot Alerts")
        print(f" | Último preço: {close.iloc[-1]:.4f}")
        print(f" | Trailing stop: {trailing_stop.iloc[-1]:.4f}")
        print(f" | Decisão: {decision}")
        print("-------")

    return decision