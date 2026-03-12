import pandas as pd

BUY = "BUY"
SELL = "SELL"
HOLD = None


def getMovingAverageAntecipationTradeStrategy(
    bot=None,
    stock_data: pd.DataFrame = None,
    volatility_factor: float = 1.2,
    fast_window: int = 7,
    slow_window: int = 40,
    verbose: bool = True
):

    if stock_data is None or len(stock_data) < slow_window:
        if verbose:
            print("❌ Dados insuficientes para calcular médias móveis.")
        return HOLD

    stock_data = stock_data.copy()

    # Médias móveis
    stock_data["ma_fast"] = stock_data["close_price"].rolling(window=fast_window).mean()
    stock_data["ma_slow"] = stock_data["close_price"].rolling(window=slow_window).mean()

    # Volatilidade
    stock_data["volatility"] = stock_data["close_price"].rolling(window=slow_window).std()

    stock_data.dropna(subset=["ma_fast", "ma_slow", "volatility"], inplace=True)

    if len(stock_data) < slow_window:
        if verbose:
            print("⚠️ Poucos dados após limpeza.")
        return HOLD

    # Últimos valores
    last_ma_fast = stock_data["ma_fast"].iloc[-1]
    prev_ma_fast = stock_data["ma_fast"].iloc[-3]

    last_ma_slow = stock_data["ma_slow"].iloc[-1]
    prev_ma_slow = stock_data["ma_slow"].iloc[-3]

    last_volatility = stock_data["volatility"].iloc[-1]

    fast_gradient = last_ma_fast - prev_ma_fast
    slow_gradient = last_ma_slow - prev_ma_slow

    current_difference = abs(last_ma_fast - last_ma_slow)

    decision = HOLD

    if current_difference < last_volatility * volatility_factor:

        if fast_gradient > 0 and fast_gradient > slow_gradient:
            decision = BUY

        elif fast_gradient < 0 and fast_gradient < slow_gradient:
            decision = SELL

    if verbose:

        print("-------")
        print("📊 Estratégia: Moving Average Antecipation")
        print(f" | MA Fast: {last_ma_fast:.3f}")
        print(f" | MA Slow: {last_ma_slow:.3f}")
        print(f" | Volatilidade: {last_volatility:.5f}")
        print(f" | Diferença atual: {current_difference:.5f}")
        print(f" | Gradiente Fast: {fast_gradient:.5f}")
        print(f" | Gradiente Slow: {slow_gradient:.5f}")
        print(f" | Decisão: {decision}")
        print("-------")

    return decision