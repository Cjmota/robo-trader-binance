import pandas as pd

BUY = "BUY"
SELL = "SELL"
HOLD = None


def getMovingAverageTradeStrategy(
    bot=None,
    stock_data: pd.DataFrame = None,
    fast_window: int = 7,
    slow_window: int = 40,
    verbose: bool = True
):
    """
    Estratégia de Médias Móveis Simples
    """

    if stock_data is None or len(stock_data) < slow_window:
        if verbose:
            print("⚠️ Dados insuficientes.")
        return HOLD

    stock_data = stock_data.copy()

    # médias móveis
    stock_data["ma_fast"] = stock_data["close_price"].rolling(window=fast_window).mean()
    stock_data["ma_slow"] = stock_data["close_price"].rolling(window=slow_window).mean()

    stock_data.dropna(subset=["ma_fast", "ma_slow"], inplace=True)

    if len(stock_data) < slow_window:
        if verbose:
            print("⚠️ Dados insuficientes após limpeza.")
        return HOLD

    last_ma_fast = stock_data["ma_fast"].iloc[-1]
    last_ma_slow = stock_data["ma_slow"].iloc[-1]

    decision = HOLD

    if last_ma_fast > last_ma_slow:
        decision = BUY

    elif last_ma_fast < last_ma_slow:
        decision = SELL

    if verbose:

        print("-------")
        print("📊 Estratégia: Moving Average Simples")
        print(f" | MA Fast: {last_ma_fast:.3f}")
        print(f" | MA Slow: {last_ma_slow:.3f}")
        print(f" | Decisão: {decision}")
        print("-------")

    return decision