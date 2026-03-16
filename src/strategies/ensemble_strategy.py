from src.strategies.vortex_strategy import getVortexTradeStrategy
from src.strategies.moving_average import getMovingAverageTradeStrategy
from src.strategies.rsi_strategy import getRsiTradeStrategy
from src.strategies.ut_bot_alerts import utBotAlerts
from src.strategies.ton_strategy_v3 import getAdvancedTradeStrategy_v3
from src.strategies.ma_rsi_volume_strategy import getMovingAverageRSIVolumeStrategy

from src.strategies.regime_detector import detectMarketRegime

BUY = "BUY"
SELL = "SELL"
HOLD = None


def runEnsembleStrategy(bot, stock_data, verbose=True):

    regime = detectMarketRegime(stock_data)

    score = 0
    signals = []

    def apply_weight(signal, weight):

        nonlocal score

        signals.append(signal)

        if signal == BUY:
            score += weight

        elif signal == SELL:
            score -= weight

    # -----------------------------
    # TREND MARKET

    if regime == "TREND":

        apply_weight(getVortexTradeStrategy(stock_data=stock_data), 2)
        apply_weight(getMovingAverageTradeStrategy(stock_data=stock_data), 1)
        apply_weight(getAdvancedTradeStrategy_v3(stock_data=stock_data), 2)

    # -----------------------------
    # RANGE MARKET

    elif regime == "RANGE":

        apply_weight(getRsiTradeStrategy(stock_data=stock_data), 1)
        apply_weight(getMovingAverageRSIVolumeStrategy(stock_data=stock_data), 1)

    # -----------------------------
    # OUTROS REGIMES

    else:

        apply_weight(utBotAlerts(stock_data=stock_data), 1)
        apply_weight(getVortexTradeStrategy(stock_data=stock_data), 2)

    if verbose:

        print("📊 Regime:", regime)
        print("📊 Signals:", signals)
        print("📊 Score:", score)

    if score > 0:
        return BUY

    if score < 0:
        return SELL

    return HOLD