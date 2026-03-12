import pandas as pd
from src.indicators import Indicators

BUY = "BUY"
SELL = "SELL"
HOLD = None


def getVortexTradeStrategy(
    bot=None,
    stock_data: pd.DataFrame = None,
    window: int = 14,
    verbose: bool = True
):

    if stock_data is None or len(stock_data) < window + 5:
        return HOLD

    stock_data = stock_data.copy()

    # calcula vortex
    stock_data["VI+"] = Indicators.getVortex(stock_data, window=window, positive=True)
    stock_data["VI-"] = Indicators.getVortex(stock_data, window=window, positive=False)

    vi_plus = stock_data["VI+"]
    vi_minus = stock_data["VI-"]

    last_vi_plus = vi_plus.iloc[-1]
    last_vi_minus = vi_minus.iloc[-1]

    decision = HOLD

    # filtro de força
    STRONG_TREND_THRESHOLD = 1.05

    if last_vi_plus > last_vi_minus and last_vi_plus >= STRONG_TREND_THRESHOLD:
        decision = BUY

    elif last_vi_minus > last_vi_plus and last_vi_minus >= STRONG_TREND_THRESHOLD:
        decision = SELL

    if verbose:

        print("-------")
        print("📊 Estratégia: Vortex")
        print(f" | VI+: {last_vi_plus:.3f}")
        print(f" | VI-: {last_vi_minus:.3f}")
        print(f" | Decisão: {decision}")
        print("-------")

    return decision