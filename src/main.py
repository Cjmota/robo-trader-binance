import threading
import json
import time
import os
import logging

import pytz
br_tz = pytz.timezone("America/Sao_Paulo")
from datetime import datetime

from src.modules.BinanceTraderBot import BinanceTraderBot
from binance.client import Client
from src.Models.StockStartModel import StockStartModel

from src.strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from src.strategies.moving_average import getMovingAverageTradeStrategy
from src.strategies.rsi_strategy import getRsiTradeStrategy
from src.strategies.vortex_strategy import getVortexTradeStrategy
from src.strategies.ma_rsi_volume_strategy import getMovingAverageRSIVolumeStrategy

from dotenv import load_dotenv
load_dotenv()

print("API KEY carregada:", bool(os.getenv("BINANCE_API_KEY")))
print("API SECRET carregada:", bool(os.getenv("BINANCE_SECRET_KEY")))


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app", "config.json")

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")
TESTNET = False

BOT_RUNNING = False
CURRENT_TRADER = None
bot_thread = None

TRADE_HISTORY = []

BINANCE_CLIENT = None

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def reload_runtime_config(bot):
    new_config = load_config()

    # Estratégias
    bot.main_strategy = strategy_map[new_config["MAIN_STRATEGY"]]
    bot.main_strategy_args = new_config.get("MAIN_STRATEGY_ARGS", {})

    bot.fallback_strategy = strategy_map[new_config["FALLBACK_STRATEGY"]]
    bot.fallback_strategy_args = new_config.get("FALLBACK_STRATEGY_ARGS", {})

    # Parâmetros de risco
    bot.acceptable_loss_percentage = new_config["ACCEPTABLE_LOSS_PERCENTAGE"] / 100
    bot.stop_loss_percentage = new_config["STOP_LOSS_PERCENTAGE"] / 100

    # Tempos
    bot.time_to_trade = new_config["TEMPO_ENTRE_TRADES"]
    bot.delay_after_order = new_config["DELAY_ENTRE_ORDENS"]

config = load_config()  # 🔥 AGORA O BOT LÊ O JSON

# 🔥 Estratégias dinâmicas vindas do dashboard
strategy_map = {
    "getVortexTradeStrategy": getVortexTradeStrategy,
    "getMovingAverageTradeStrategy": getMovingAverageTradeStrategy,
    "getRsiTradeStrategy": getRsiTradeStrategy,
    "getMovingAverageRSIVolumeStrategy": getMovingAverageRSIVolumeStrategy,
}

MAIN_STRATEGY = strategy_map[config["MAIN_STRATEGY"]]
MAIN_STRATEGY_ARGS = config.get("MAIN_STRATEGY_ARGS", {})

FALLBACK_ACTIVATED = config["FALLBACK_ACTIVATED"]
FALLBACK_STRATEGY = strategy_map[config["FALLBACK_STRATEGY"]]
FALLBACK_STRATEGY_ARGS = config.get("FALLBACK_STRATEGY_ARGS", {})

# Define o logger
# 🔥 Configuração segura de log
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOG_DIR, "trading_bot.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)    


# fmt: off
# -------------------------------------------------------------------------------------------------
# 🟢🟢🟢 CONFIGURAÇÕES - PODEM ALTERAR - INICIO 🟢🟢🟢



# Ajustes de LOSS PROTECTION
ACCEPTABLE_LOSS_PERCENTAGE = config["ACCEPTABLE_LOSS_PERCENTAGE"]# (Em base 100%) O quando o bot aceita perder de % (se for negativo, o bot só aceita lucro) 
STOP_LOSS_PERCENTAGE = config["STOP_LOSS_PERCENTAGE"]  # (Em base 100%) % Máxima de loss que ele aceita para vender à mercado independente      

# Ajustes de TAKE PROFIT (Em base 100%)                        
TP_AT_PERCENTAGE =      [2, 4, 8]       # Em [X%, Y%]                       
TP_AMOUNT_PERCENTAGE =  [50, 50, 100]   # Vende [A%, B%]

# ------------------------------------------------------------------
# ⌛ AJUSTES DE TEMPO

# Périodo do candle análisado
CANDLE_PERIOD = getattr(Client, config["CANDLE_PERIOD"].split(".")[-1])

TEMPO_ENTRE_TRADES = config["TEMPO_ENTRE_TRADES"]            # Tempo que o bot espera para verificar o mercado (em segundos)
DELAY_ENTRE_ORDENS = config["DELAY_ENTRE_ORDENS"]           # Tempo que o bot espera depois de realizar uma ordem de compra ou venda (ajuda a diminuir trades de borda)


# ------------------------------------------------------------------
# 🪙 MOEDAS NEGOCIADAS

stocks_traded_list = []

for stock in config["stocks_traded_list"]:
    asset = StockStartModel(
        stockCode=stock["stockCode"],
        operationCode=stock["operationCode"],
        tradedQuantity=stock["capital"],
        mainStrategy=MAIN_STRATEGY,
        mainStrategyArgs=MAIN_STRATEGY_ARGS,
        fallbackStrategy=FALLBACK_STRATEGY,
        fallbackStrategyArgs=FALLBACK_STRATEGY_ARGS,
        candlePeriod=CANDLE_PERIOD,
        stopLossPercentage=STOP_LOSS_PERCENTAGE,
        tempoEntreTrades=TEMPO_ENTRE_TRADES,
        delayEntreOrdens=DELAY_ENTRE_ORDENS,
        acceptableLossPercentage=ACCEPTABLE_LOSS_PERCENTAGE,
        fallBackActivated=FALLBACK_ACTIVATED,
        takeProfitAtPercentage=TP_AT_PERCENTAGE,
        takeProfitAmountPercentage=TP_AMOUNT_PERCENTAGE,
    )
    stocks_traded_list.append(asset)

THREAD_LOCK = True # True = Executa 1 moeda por vez | False = Executa todas simultânemaente

# 🔴🔴🔴 CONFIGURAÇÕES - FIM 🔴🔴🔴
# -------------------------------------------------------------------------------------------------

# 🔁 LOOP PRINCIPAL
# 🔁 LOOP PRINCIPAL INTELIGENTE (UMA MOEDA POR VEZ)

thread_lock = threading.Lock()


def trader_master_loop():
    global CURRENT_TRADER, BOT_RUNNING, BINANCE_CLIENT

    current_trader = None
    last_outside_log = False
    
    if BINANCE_CLIENT is None:
        BINANCE_CLIENT = Client(API_KEY, API_SECRET)

    while BOT_RUNNING:

        now = datetime.now(br_tz).hour

        # 🔴 Se passou das 20h
        if now >= 20:
            print("🛑 Fora do horário operacional.")

            if current_trader and current_trader.actual_trade_position:
                print("🛑 Encerrando posição por fim de horário.")
                current_trader.close_position_market()
                current_trader = None  # evita tentar fechar de novo

            time.sleep(60) #em vez de 300
            continue
        
        if now < 5:
            if not last_outside_log:
                print("⏰ Fora do horário operacional (05h-20h). Aguardando...")
                last_outside_log = True
            time.sleep(300)
            continue   
                    
        else:
            last_outside_log = False

        if current_trader is None:

            print("🔎 Procurando melhor oportunidade...")

            symbols = scan_market_top_symbols(BINANCE_CLIENT, limit=5)
            
            if not symbols:
                print("⚠️ Nenhuma oportunidade encontrada.")
                time.sleep(10)
                continue

            for symbol in symbols:

                stock = symbol.replace("USDT", "")

                print(f"🎯 Testando ativo: {symbol}")

                try:

                    trader = BinanceTraderBot(
                        stock_code=stock,
                        operation_code=symbol,
                        traded_quantity=20,
                        traded_percentage=100,
                        candle_period=CANDLE_PERIOD,
                        api_key=API_KEY,
                        api_secret=API_SECRET,
                        testnet=TESTNET,
                        time_to_trade=TEMPO_ENTRE_TRADES,
                        delay_after_order=DELAY_ENTRE_ORDENS,
                        acceptable_loss_percentage=ACCEPTABLE_LOSS_PERCENTAGE,
                        stop_loss_percentage=STOP_LOSS_PERCENTAGE,
                        fallback_activated=FALLBACK_ACTIVATED,
                        take_profit_at_percentage=TP_AT_PERCENTAGE,
                        take_profit_amount_percentage=TP_AMOUNT_PERCENTAGE,
                        main_strategy=MAIN_STRATEGY,
                        main_strategy_args=MAIN_STRATEGY_ARGS,
                        fallback_strategy=FALLBACK_STRATEGY,
                        fallback_strategy_args=FALLBACK_STRATEGY_ARGS,
                    )

                    trader.updateAllData()

                    decision = trader.getFinalDecisionStrategy()

                    if decision is True:
                        print(f"🚀 Oportunidade encontrada em {symbol}")
                        current_trader = trader
                        break

                except Exception as e:
                    print(f"Erro ao analisar {symbol}: {e}")

        if current_trader:
            CURRENT_TRADER = current_trader
            BINANCE_CLIENT = current_trader.client_binance
            current_trader.execute()

            if not current_trader.actual_trade_position:
    
                # 🔥 Registrar trade finalizado
                if hasattr(current_trader, "last_trade_profit"):
                    TRADE_HISTORY.append({
                        "timestamp": time.time(),
                        "asset": current_trader.operation_code,
                        "profit": current_trader.last_trade_profit
                    })

                current_trader = None            
            

        time.sleep(5)

    print("🛑 Loop do robô finalizado.")


# Inicia o robô principal
if __name__ == "__main__":
    print("🤖 Master Trader iniciado (modo multi-moedas inteligente).")
    BOT_RUNNING = True
    trader_master_loop()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nPrograma encerrado pelo usuário.")

def safe_trader_master_loop():
    while BOT_RUNNING:
        try:
            print("🚀 Iniciando ciclo do robô...")
            trader_master_loop()

        except Exception as e:
            print("⚠️ Erro inesperado no robô:", e)

            logging.error(
                f"Erro inesperado no robô: {e}",
                exc_info=True
            )

            print("🔄 Reiniciando robô em 10 segundos...")
            time.sleep(10)
            
    
def symbol_to_stock(symbol):

    if symbol.endswith("USDT"):
        return symbol.replace("USDT", "")

    return symbol

def scan_market_top_symbols(client, limit=20):

    print("🔎 Escaneando mercado inteligente...")

    try:

        tickers = client.get_ticker()

        if not tickers:
            return []

        candidates = []

        for t in tickers:

            symbol = t["symbol"]

            if not symbol.endswith("USDT"):
                continue

            volume = float(t["quoteVolume"])
            price_change = abs(float(t["priceChangePercent"]))

            # ignorar moedas com pouco volume
            if volume < 5_000_000:
                continue

            try:
                candles = client.get_klines(
                    symbol=symbol,
                    interval=Client.KLINE_INTERVAL_5MINUTE,
                    limit=20
                )

                closes = [float(c[4]) for c in candles]

                if not closes:
                    continue

                min_price = min(closes)
                max_price = max(closes)

                if min_price == 0:
                    continue

                volatility = (max_price - min_price) / min_price

            except:
                continue

            # score profissional
            score = volume * price_change * volatility

            candidates.append((symbol, score))

        candidates.sort(key=lambda x: x[1], reverse=True)

        best = [s[0] for s in candidates[:limit]]

        print("🔥 TOP OPORTUNIDADES:", best)

        return best

    except Exception as e:

        print("Erro no scanner:", e)

        return []