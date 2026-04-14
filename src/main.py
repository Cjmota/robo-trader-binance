import threading
import time
from modules.BinanceTraderBot import BinanceTraderBot
from binance.client import Client
from Models.StockStartModel import StockStartModel
from dashboard import bot_control
from dashboard import app
import logging
import os

# Define o logger
logging.basicConfig(
    filename="src/logs/trading_bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

from strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from strategies.moving_average import getMovingAverageTradeStrategy

# from strategies.vortex_strategy import getVortexTradeStrategy
from strategies.rsi_strategy import getRsiTradeStrategy
from strategies.vortex_strategy import getVortexTradeStrategy
from strategies.ma_rsi_volume_strategy import getMovingAverageRSIVolumeStrategy

# fmt: off
# -------------------------------------------------------------------------------------------------
# 🟢🟢🟢 CONFIGURAÇÕES - PODEM ALTERAR - INICIO 🟢🟢🟢

# ------------------------------------------------------------------
# 🚀 AJUSTES DE ESTRATÉGIA 🚀

# 🏆 ESTRATÉGIA PRINCIPAL 🏆

# MAIN_STRATEGY = getMovingAverageAntecipationTradeStrategy
# MAIN_STRATEGY_ARGS = {"volatility_factor": 0.5, # Interfere na antecipação e nos lances de compra de venda limitados 
#                       "fast_window": 9,
#                       "slow_window": 21}

MAIN_STRATEGY = getVortexTradeStrategy
MAIN_STRATEGY_ARGS = {}

# MAIN_STRATEGY = getVortexTradeStrategy
# MAIN_STRATEGY_ARGS = {}

# MAIN_STRATEGY = getMovingAverageRSIVolumeStrategy
# MAIN_STRATEGY_ARGS = {  "fast_window":  9,
#                         "slow_window":  21,
#                         "rsi_window":  14,
#                         "rsi_overbought":  70,
#                         "rsi_oversold":  30,
#                         "volume_multiplier":  1.5
#                         }

# MAIN_STRATEGY = getRsiTradeStrategy
# MAIN_STRATEGY_ARGS = {}

# -----------------

# 🥈 ESTRATÉGIA DE FALLBACK (reserva) 🥈

FALLBACK_ACTIVATED  = True      
FALLBACK_STRATEGY = getMovingAverageTradeStrategy
FALLBACK_STRATEGY_ARGS = {}



# ------------------------------------------------------------------
# 🛠️ AJUSTES TÉCNICOS 🛠️

# Ajustes de LOSS PROTECTION
ACCEPTABLE_LOSS_PERCENTAGE  = 0         # (Em base 100%) O quando o bot aceita perder de % (se for negativo, o bot só aceita lucro)
STOP_LOSS_PERCENTAGE        = 3.5       # (Em base 100%) % Máxima de loss que ele aceita para vender à mercado independente

# Ajustes de TAKE PROFIT (Em base 100%)                        
TP_AT_PERCENTAGE =      [2, 4, 8]       # Em [X%, Y%]                       
TP_AMOUNT_PERCENTAGE =  [50, 50, 100]   # Vende [A%, B%]


# ------------------------------------------------------------------
# ⌛ AJUSTES DE TEMPO

# CANDLE_PERIOD = Client.KLINE_INTERVAL_1HOUR # Périodo do candle análisado
CANDLE_PERIOD = Client.KLINE_INTERVAL_15MINUTE # Périodo do candle análisado

TEMPO_ENTRE_TRADES          = 30 * 60            # Tempo que o bot espera para verificar o mercado (em segundos)
DELAY_ENTRE_ORDENS          = 60 * 60           # Tempo que o bot espera depois de realizar uma ordem de compra ou venda (ajuda a diminuir trades de borda)


# ------------------------------------------------------------------
# 🪙 MOEDAS NEGOCIADAS

XRP_USDT = StockStartModel(  stockCode = "XRP",
                            operationCode = "XRPUSDT",
                            tradedQuantity = 3,
                            mainStrategy = MAIN_STRATEGY, mainStrategyArgs = MAIN_STRATEGY_ARGS, fallbackStrategy = FALLBACK_STRATEGY, fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
                            candlePeriod = CANDLE_PERIOD, stopLossPercentage = STOP_LOSS_PERCENTAGE, tempoEntreTrades = TEMPO_ENTRE_TRADES, delayEntreOrdens = DELAY_ENTRE_ORDENS, acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, fallBackActivated= FALLBACK_ACTIVATED, takeProfitAtPercentage=TP_AT_PERCENTAGE, takeProfitAmountPercentage=TP_AMOUNT_PERCENTAGE)

SOL_USDT = StockStartModel(  stockCode = "SOL",
                            operationCode = "SOLUSDT",
                            tradedQuantity = 0.1,
                            mainStrategy = MAIN_STRATEGY, mainStrategyArgs = MAIN_STRATEGY_ARGS, fallbackStrategy = FALLBACK_STRATEGY, fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
                            candlePeriod = CANDLE_PERIOD, stopLossPercentage = STOP_LOSS_PERCENTAGE, tempoEntreTrades = TEMPO_ENTRE_TRADES, delayEntreOrdens = DELAY_ENTRE_ORDENS, acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, fallBackActivated= FALLBACK_ACTIVATED, takeProfitAtPercentage=TP_AT_PERCENTAGE, takeProfitAmountPercentage=TP_AMOUNT_PERCENTAGE)

ADA_USDT = StockStartModel(  stockCode = "ADA",
                            operationCode = "ADAUSDT",
                            tradedQuantity = 10,
                            mainStrategy = MAIN_STRATEGY, mainStrategyArgs = MAIN_STRATEGY_ARGS, fallbackStrategy = FALLBACK_STRATEGY, fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
                            candlePeriod = CANDLE_PERIOD, stopLossPercentage = STOP_LOSS_PERCENTAGE, tempoEntreTrades = TEMPO_ENTRE_TRADES, delayEntreOrdens = DELAY_ENTRE_ORDENS, acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, fallBackActivated= FALLBACK_ACTIVATED, takeProfitAtPercentage=TP_AT_PERCENTAGE, takeProfitAmountPercentage=TP_AMOUNT_PERCENTAGE)

BTC_USDT = StockStartModel(  stockCode = "BTC",
                            operationCode = "BTCUSDT",
                            tradedQuantity = 0.001,
                            mainStrategy = MAIN_STRATEGY, mainStrategyArgs = MAIN_STRATEGY_ARGS, fallbackStrategy = FALLBACK_STRATEGY, fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
                            candlePeriod = CANDLE_PERIOD, stopLossPercentage = STOP_LOSS_PERCENTAGE, tempoEntreTrades = TEMPO_ENTRE_TRADES, delayEntreOrdens = DELAY_ENTRE_ORDENS, acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, fallBackActivated= FALLBACK_ACTIVATED, takeProfitAtPercentage=TP_AT_PERCENTAGE, takeProfitAmountPercentage=TP_AMOUNT_PERCENTAGE)


# ⤵️ Array que DEVE CONTER as moedas que serão negociadas
stocks_traded_list = [
    ADA_USDT,
    SOL_USDT
]

THREAD_LOCK = True # True = Executa 1 moeda por vez | False = Executa todas simultânemaente

# 🔴🔴🔴 CONFIGURAÇÕES - FIM 🔴🔴🔴
# -------------------------------------------------------------------------------------------------



# 🔁 LOOP PRINCIPAL

thread_lock = threading.Lock()

def trader_loop(stockStart: StockStartModel):
    MaTrader = BinanceTraderBot(stock_code = stockStart.stockCode
                                , operation_code = stockStart.operationCode
                                , traded_quantity = stockStart.tradedQuantity
                                , traded_percentage = stockStart.tradedPercentage
                                , candle_period = stockStart.candlePeriod
                                , time_to_trade = stockStart.tempoEntreTrades
                                , delay_after_order = stockStart.delayEntreOrdens
                                , acceptable_loss_percentage = stockStart.acceptableLossPercentage
                                , stop_loss_percentage = stockStart.stopLossPercentage
                                , fallback_activated = stockStart.fallBackActivated
                                , take_profit_at_percentage = stockStart.takeProfitAtPercentage
                                , take_profit_amount_percentage= stockStart.takeProfitAmountPercentage
                                , main_strategy = stockStart.mainStrategy
                                , main_strategy_args =  stockStart.mainStrategyArgs
                                , fallback_strategy = stockStart.fallbackStrategy
                                , fallback_strategy_args = stockStart.fallbackStrategyArgs)
    

    total_executed:int = 1

    while True:

        if not bot_control["running"]:
            print(f"⏸ [{MaTrader.operation_code}] aguardando ativação...")

            while not bot_control["running"]:
                time.sleep(1)

            print(f"▶ [{MaTrader.operation_code}] retomando operação")

        MaTrader.execute()

        sleep_time = int(MaTrader.time_to_sleep)

        for _ in range(sleep_time):
            if not bot_control["running"]:
                print(f"⏸ [{MaTrader.operation_code}] pausado durante sleep")
                break

            time.sleep(1)

# Criando e iniciando uma thread para cada objeto
threads = []

for asset in stocks_traded_list:
    thread = threading.Thread(target=trader_loop, args=(asset,))
    thread.daemon = True  # Permite finalizar as threads ao encerrar o programa
    thread.start()
    threads.append(thread)

print("Threads iniciadas para todos os ativos.")

# O programa principal continua executando sem bloquear
try:
    while True:
        time.sleep(1)  # Mantenha o programa rodando
except KeyboardInterrupt:
    print("\nPrograma encerrado pelo usuário.")

# -----------------------------------------------------------------


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# fmt: on
