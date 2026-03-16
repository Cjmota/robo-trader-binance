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
    Estratégia de Médias Móveis Simples (com detecção de cruzamento)
    """

    if stock_data is None or len(stock_data) < slow_window:
        if verbose:
            print("⚠️ Dados insuficientes.")
        return HOLD

    stock_data = stock_data.copy()

    # ---------------------------
    # Médias móveis

    stock_data["ma_fast"] = stock_data["close_price"].rolling(window=fast_window).mean()
    stock_data["ma_slow"] = stock_data["close_price"].rolling(window=slow_window).mean()

    stock_data.dropna(subset=["ma_fast", "ma_slow"], inplace=True)

    if len(stock_data) < 3:
        if verbose:
            print("⚠️ Poucos dados após limpeza.")
        return HOLD

    # ---------------------------
    # Valores atuais

    last_ma_fast = stock_data["ma_fast"].iloc[-1]
    last_ma_slow = stock_data["ma_slow"].iloc[-1]

    prev_ma_fast = stock_data["ma_fast"].iloc[-2]
    prev_ma_slow = stock_data["ma_slow"].iloc[-2]

    # ---------------------------
    # Momentum simples

    momentum = (
        stock_data["close_price"].iloc[-1] -
        stock_data["close_price"].iloc[-3]
    ) / stock_data["close_price"].iloc[-3]

    decision = HOLD

    # ---------------------------
    # Cruzamento para cima

    if prev_ma_fast <= prev_ma_slow and last_ma_fast > last_ma_slow and momentum > 0:
        decision = BUY

    # ---------------------------
    # Cruzamento para baixo

    elif prev_ma_fast >= prev_ma_slow and last_ma_fast < last_ma_slow and momentum < 0:
        decision = SELL

    # ---------------------------
    # Log

    if verbose:

        print("-------")
        print("📊 Estratégia: Moving Average Simples")
        print(f" | MA Fast: {last_ma_fast:.3f}")
        print(f" | MA Slow: {last_ma_slow:.3f}")
        print(f" | Momentum: {momentum:.4f}")
        print(f" | Decisão: {decision}")
        print("-------")

    return decision