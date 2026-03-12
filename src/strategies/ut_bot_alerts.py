import numpy as np
import pandas as pd

BUY = "BUY"
SELL = "SELL"
HOLD = None


def calculate_atr(high, low, close, period=10):

    tr1 = high - low
    tr2 = np.abs(high - close.shift(1))
    tr3 = np.abs(low - close.shift(1))

    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = tr.rolling(window=period).mean()

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

    trailing_stop = pd.Series(np.zeros(len(close)), index=close.index)

    for i in range(1, len(close)):

        if close.iloc[i] > trailing_stop.iloc[i - 1] and close.iloc[i - 1] > trailing_stop.iloc[i - 1]:

            trailing_stop.iloc[i] = max(
                trailing_stop.iloc[i - 1],
                close.iloc[i] - atr_multiplier * atr.iloc[i]
            )

        elif close.iloc[i] < trailing_stop.iloc[i - 1] and close.iloc[i - 1] < trailing_stop.iloc[i - 1]:

            trailing_stop.iloc[i] = min(
                trailing_stop.iloc[i - 1],
                close.iloc[i] + atr_multiplier * atr.iloc[i]
            )

        else:

            trailing_stop.iloc[i] = (
                close.iloc[i] - atr_multiplier * atr.iloc[i]
                if close.iloc[i] > trailing_stop.iloc[i - 1]
                else close.iloc[i] + atr_multiplier * atr.iloc[i]
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
        print(f" | Decisão: {decision}")
        print("-------")

    return decision