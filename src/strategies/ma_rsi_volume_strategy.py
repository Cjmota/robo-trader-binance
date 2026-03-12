import pandas as pd

BUY = "BUY"
SELL = "SELL"
HOLD = None


def getMovingAverageRSIVolumeStrategy(
    bot=None,
    stock_data: pd.DataFrame = None,
    fast_window: int = 7,
    slow_window: int = 40,
    rsi_window: int = 14,
    rsi_overbought: int = 70,
    rsi_oversold: int = 30,
    volume_multiplier: float = 1.5,
    verbose: bool = True,
):
    """
    Estratégia de Médias Móveis com confirmação de RSI e Volume
    """

    stock_data = stock_data.copy()

    # Médias móveis
    stock_data["ma_fast"] = stock_data["close_price"].rolling(window=fast_window).mean()
    stock_data["ma_slow"] = stock_data["close_price"].rolling(window=slow_window).mean()

    # RSI
    delta = stock_data["close_price"].diff()

    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_window).mean()

    rs = gain / loss
    stock_data["rsi"] = 100 - (100 / (1 + rs))

    # Volume médio
    stock_data["volume_avg"] = stock_data["volume"].rolling(window=slow_window).mean()

    stock_data.dropna(subset=["ma_fast", "ma_slow", "rsi", "volume_avg"], inplace=True)

    if len(stock_data) < slow_window:

        if verbose:
            print("⚠️ Dados insuficientes")

        return HOLD

    last_ma_fast = stock_data["ma_fast"].iloc[-1]
    last_ma_slow = stock_data["ma_slow"].iloc[-1]
    last_rsi = stock_data["rsi"].iloc[-1]
    last_volume = stock_data["volume"].iloc[-1]
    last_volume_avg = stock_data["volume_avg"].iloc[-1]

    # Compra
    buy_condition = (
        (last_ma_fast > last_ma_slow)
        and (last_rsi > rsi_oversold)
        and (last_volume > (volume_multiplier * last_volume_avg))
    )

    # Venda
    sell_condition = (
        (last_ma_fast < last_ma_slow)
        or (last_rsi > rsi_overbought)
    )

    if buy_condition:
        decision = BUY
    elif sell_condition:
        decision = SELL
    else:
        decision = HOLD

    if verbose:

        print("-------")
        print("📊 MA + RSI + Volume")
        print(f" | MA Fast: {last_ma_fast:.3f}")
        print(f" | MA Slow: {last_ma_slow:.3f}")
        print(f" | RSI: {last_rsi:.2f}")
        print(f" | Volume: {last_volume:.2f}")
        print(f" | Volume Avg: {last_volume_avg:.2f}")
        print(f" | Decisão: {decision}")
        print("-------")

    return decision
