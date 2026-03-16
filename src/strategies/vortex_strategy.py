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

    df = stock_data.copy()

    # -------------------------
    # calcular vortex

    df["VI+"] = Indicators.getVortex(df, window=window, positive=True)
    df["VI-"] = Indicators.getVortex(df, window=window, positive=False)

    df.dropna(inplace=True)

    if len(df) < 3:
        return HOLD

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    last_vi_plus = latest["VI+"]
    last_vi_minus = latest["VI-"]

    prev_vi_plus = prev["VI+"]
    prev_vi_minus = prev["VI-"]

    decision = HOLD

    # força mínima da tendência
    TREND_DIFF = 0.05

    # -------------------------
    # BUY: cruzamento VI+

    if (
        prev_vi_plus <= prev_vi_minus
        and last_vi_plus > last_vi_minus
        and (last_vi_plus - last_vi_minus) > TREND_DIFF
    ):
        decision = BUY

    # -------------------------
    # SELL: cruzamento VI-

    elif (
        prev_vi_minus <= prev_vi_plus
        and last_vi_minus > last_vi_plus
        and (last_vi_minus - last_vi_plus) > TREND_DIFF
    ):
        decision = SELL

    # -------------------------
    # LOG

    if verbose:

        print("-------")
        print("📊 Estratégia: Vortex")
        print(f" | VI+: {last_vi_plus:.3f}")
        print(f" | VI-: {last_vi_minus:.3f}")
        print(f" | Diferença: {abs(last_vi_plus - last_vi_minus):.3f}")
        print(f" | Decisão: {decision}")
        print("-------")

    return decision