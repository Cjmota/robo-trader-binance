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

        signals.append(getVortexTradeStrategy(stock_data=stock_data))
        signals.append(getMovingAverageTradeStrategy(stock_data=stock_data))
        signals.append(getAdvancedTradeStrategy_v3(stock_data=stock_data))

    elif regime == "RANGE":

        signals.append(getRsiTradeStrategy(stock_data=stock_data))
        signals.append(getMovingAverageRSIVolumeStrategy(stock_data=stock_data))

    else:

        signals.append(utBotAlerts(stock_data=stock_data))
        signals.append(getVortexTradeStrategy(stock_data=stock_data))

    buy = signals.count(BUY)
    sell = signals.count(SELL)

    if verbose:
        print("📊 Regime:", regime)
        print("📊 Signals:", signals)

    if buy > sell:
        return BUY

    if sell > buy:
        return SELL

    return HOLD