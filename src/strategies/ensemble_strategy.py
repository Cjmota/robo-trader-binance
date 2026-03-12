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

    signals = []

    if regime == "TREND":

        signals.append(getVortexTradeStrategy(bot=bot, stock_data=stock_data))
        signals.append(getMovingAverageTradeStrategy(bot=bot, stock_data=stock_data))
        signals.append(getAdvancedTradeStrategy_v3(bot=bot, stock_data=stock_data))

    elif regime == "RANGE":

        signals.append(getRsiTradeStrategy(bot=bot, stock_data=stock_data))
        signals.append(getMovingAverageRSIVolumeStrategy(bot=bot, stock_data=stock_data))

    else:

        signals.append(utBotAlerts(bot=bot, stock_data=stock_data))
        signals.append(getVortexTradeStrategy(bot=bot, stock_data=stock_data))

    buy = signals.count(BUY)
    sell = signals.count(SELL)

    if verbose:
        print("📊 Regime:", regime)
        print("📊 Signals:", signals)

    if buy >= 2:
        return BUY

    if sell >= 2:
        return SELL

    return HOLD