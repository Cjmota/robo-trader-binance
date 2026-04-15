from src.modules.BinanceTraderBot import BinanceTraderBot
from binance.client import Client
from src.tests.backtestRunner import backtestRunner
from src.strategies.ut_bot_alerts import *
from src.strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from src.strategies.moving_average import getMovingAverageTradeStrategy
from src.strategies.rsi_strategy import getRsiTradeStrategy
from src.strategies.vortex_strategy import getVortexTradeStrategy
from src.strategies.ma_rsi_volume_strategy import getMovingAverageRSIVolumeStrategy

# ------------------------------------------------------------------------
# 🔎 AJUSTES BACKTESTS 🔎

STOCK_CODE = "BNX"  # Código da Criptomoeda
OPERATION_CODE = "BNXUSDT"  # Código da operação (cripto + moeda)
INITIAL_BALANCE = 1000  # Valor de investimento inicial em USDT ou BRL

# ----------------------------------------
# 📊 PERÍODO DO CANDLE, SELECIONAR 1 📊

CANDLE_PERIOD = Client.KLINE_INTERVAL_1HOUR
# CANDLE_PERIOD = Client.KLINE_INTERVAL_15MINUTE

CLANDES_RODADOS = 7 * 24

# ------------------------------------------------------------------------
# ⏬ SELEÇÃO DE ESTRATÉGIAS ⏬

devTrader = BinanceTraderBot(
    stock_code=STOCK_CODE,
    operation_code=OPERATION_CODE,
    traded_quantity=0,
    traded_percentage=100,
    candle_period=CANDLE_PERIOD,
    # volatility_factor=VOLATILITY_FACTOR,
)


devTrader.updateAllData()

print(f"\n{STOCK_CODE} - UT BOTS - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data=devTrader.stock_data,
    strategy_function=utBotAlerts,
    periods=CLANDES_RODADOS,
    initial_balance=INITIAL_BALANCE,
    atr_multiplier=2,
    atr_period=1,
    verbose=False,
)

devTrader.updateAllData()

print(f"\n{STOCK_CODE} - MA RSI e VOLUME - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data=devTrader.stock_data,
    strategy_function=getMovingAverageRSIVolumeStrategy,
    periods=CLANDES_RODADOS,
    initial_balance=INITIAL_BALANCE,
    verbose=False,
)


print(f"\n{STOCK_CODE} - MA ANTECIPATION - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data=devTrader.stock_data,
    strategy_function=getMovingAverageAntecipationTradeStrategy,
    periods=CLANDES_RODADOS,
    initial_balance=INITIAL_BALANCE,
    volatility_factor=0.5,
    fast_window=7,
    slow_window=40,
    verbose=False,
)

print(f"\n{STOCK_CODE} - MA SIMPLES FALLBACK - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data=devTrader.stock_data,
    strategy_function=getMovingAverageTradeStrategy,
    periods=CLANDES_RODADOS,
    initial_balance=INITIAL_BALANCE,
    fast_window=7,
    slow_window=40,
    verbose=False,
)

print(f"\n{STOCK_CODE} - RSI - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data=devTrader.stock_data,
    strategy_function=getRsiTradeStrategy,
    periods=CLANDES_RODADOS,
    initial_balance=INITIAL_BALANCE,
    low=30,
    high=70,
    verbose=False,
)

print(f"\n{STOCK_CODE} - VORTEX - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data=devTrader.stock_data,
    strategy_function=getVortexTradeStrategy,
    periods=CLANDES_RODADOS,
    initial_balance=INITIAL_BALANCE,
    verbose=False,
)


print("\n\n")
