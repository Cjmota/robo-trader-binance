import pandas as pd
from src.indicators.extras import Indicators

BUY = "BUY"
SELL = "SELL"
HOLD = None


def getRsiTradeStrategy(
    bot=None,
    stock_data: pd.DataFrame = None,
    low: int = 30,
    high: int = 70,
    verbose: bool = True
):

    if stock_data is None or len(stock_data) < 20:
        return HOLD

    stock_data = stock_data.copy()

    # -------------------------
    # RSI

    stock_data["RSI"] = Indicators.getRSI(
        stock_data["close_price"],
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
    # BUY: saiu da sobrevenda

    if (
        last_valley is not None
        and (last_peak is None or last_valley > last_peak)
        and prev_rsi < low
        and last_rsi > low
    ):
        decision = BUY

    # -------------------------
    # SELL: saiu da sobrecompra

    elif (
        last_peak is not None
        and (last_valley is None or last_peak > last_valley)
        and prev_rsi > high
        and last_rsi < high
    ):
        decision = SELL

    # -------------------------
    # Log

    if verbose:

        print("-------")
        print("📊 Estratégia: RSI")
        print(f" | RSI atual: {last_rsi:.2f}")
        print(f" | RSI anterior: {prev_rsi:.2f}")
        print(f" | Último vale: {last_valley}")
        print(f" | Último pico: {last_peak}")
        print(f" | Decisão: {decision}")
        print("-------")

    return decision