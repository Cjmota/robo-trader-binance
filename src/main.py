import statistics
import threading
import json
import time
import os
import logging
import math

import pytz
br_tz = pytz.timezone("America/Sao_Paulo")
from datetime import datetime

from src.modules.BinanceTraderBot import BinanceTraderBot
from binance.client import Client
from src.Models.StockStartModel import StockStartModel

from concurrent.futures import ThreadPoolExecutor

from src.utils.market_mode import detect_market_mode

from src.strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from src.strategies.moving_average import getMovingAverageTradeStrategy
from src.strategies.rsi_strategy import getRsiTradeStrategy
from src.strategies.vortex_strategy import getVortexTradeStrategy
from src.strategies.ma_rsi_volume_strategy import getMovingAverageRSIVolumeStrategy

from src.strategies.ensemble_strategy import runEnsembleStrategy

from dotenv import load_dotenv
load_dotenv()

print("API KEY carregada:", bool(os.getenv("BINANCE_API_KEY")))
print("API SECRET carregada:", bool(os.getenv("BINANCE_SECRET_KEY")))


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app", "config.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

global config  # 🔥 AGORA O BOT LÊ O JSON

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")
TESTNET = False

BOT_RUNNING = False
CURRENT_TRADER = None
bot_thread = None

TRADE_HISTORY = []

MARKET_MEMORY = {}


SCANNER_RANKING = []   # 🔥 ranking do scanner para dashboard
SCANNER_SMART_MONEY = []

config = load_config()
config["CANDLE_PERIOD"] = str(config["CANDLE_PERIOD"]).strip().lower()

LOSS_COOLDOWN = config["RISK"]["LOSS_COOLDOWN"]

ADAPTIVE_WEIGHTS = {
    "pre_pump": 3.0,
    "squeeze": 2.0,
    "orderflow": 2.0,
    "sweep": 2.0
}

BINANCE_CLIENT = None

symbol_cooldown = {}
COOLDOWN_SECONDS = config["RISK"]["SYMBOL_COOLDOWN"]

MAX_TRADES_PER_DAY = config["RISK"]["MAX_TRADES_PER_DAY"]

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

def safe_binance_call(func, *args, retries=3, delay=2, **kwargs):
    """
    Executa chamadas da Binance com retry automático
    """

    for attempt in range(retries):

        try:
            return func(*args, **kwargs)

        except Exception as e:

            print(f"⚠️ Binance erro: {e}")

            if attempt < retries - 1:

                sleep_time = delay * (attempt + 1)

                print(f"🔁 Tentando novamente em {sleep_time}s...")
                time.sleep(sleep_time)

            else:

                print("❌ Falha definitiva na chamada da Binance")

                return None

# 🔥 Estratégias dinâmicas vindas do dashboard
strategy_map = {
    "getVortexTradeStrategy": getVortexTradeStrategy,
    "getMovingAverageTradeStrategy": getMovingAverageTradeStrategy,
    "getRsiTradeStrategy": getRsiTradeStrategy,
    "getMovingAverageRSIVolumeStrategy": getMovingAverageRSIVolumeStrategy,
    "runEnsembleStrategy": runEnsembleStrategy
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
#TP_AT_PERCENTAGE = [2, 4, 8]       # Em [X%, Y%]                       
#TP_AMOUNT_PERCENTAGE = [50, 50, 100]   # Vende [A%, B%]

TP_AT_PERCENTAGE = config["TP_AT_PERCENTAGE"]
TP_AMOUNT_PERCENTAGE = config["TP_AMOUNT_PERCENTAGE"]

# ------------------------------------------------------------------
# ⌛ AJUSTES DE TEMPO

# Périodo do candle análisado
CANDLE_PERIOD = config["CANDLE_PERIOD"]

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


# 🔴🔴🔴 CONFIGURAÇÕES - FIM 🔴🔴🔴
# -------------------------------------------------------------------------------------------------

last_traded_symbol = None

# 🔁 LOOP PRINCIPAL
# 🔁 LOOP PRINCIPAL INTELIGENTE (UMA MOEDA POR VEZ)

thread_lock = threading.Lock()


def trader_master_loop():
    
    current_trader = BinanceTraderBot(
        stock_code="BTC",
        operation_code="BTCUSDT",
        traded_quantity=config["stocks_traded_list"][0]["capital"],
        traded_percentage=100,
        candle_period=CANDLE_PERIOD,
        api_key=API_KEY,
        api_secret=API_SECRET,
        config=config,
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
        
    global CURRENT_TRADER, BOT_RUNNING, BINANCE_CLIENT, last_traded_symbol

    last_outside_log = False
    last_trade_logged = False
    
    try:
        if BINANCE_CLIENT is None:
            BINANCE_CLIENT = Client(API_KEY, API_SECRET)

    except Exception as e:
        print("Erro conectando Binance:", e)
        time.sleep(10)
        return

    while BOT_RUNNING:

        try:
            if current_trader:
                reload_runtime_config(current_trader)
        except Exception as e:
            print("Erro ao recarregar config:", e)

        # limpeza memória
        if len(MARKET_MEMORY) > 200:
            MARKET_MEMORY.clear()

        # ping conexão
        try:
            BINANCE_CLIENT.ping()
        except Exception as e:

            print("🔄 Reconectando Binance...", e)

            try:
                BINANCE_CLIENT = Client(API_KEY, API_SECRET)
            except Exception as reconnect_error:
                print("❌ Falha na reconexão:", reconnect_error)
                time.sleep(10)
                continue

        now = datetime.now(br_tz).hour

        # limite diário
        if len(TRADE_HISTORY) >= MAX_TRADES_PER_DAY:
            print("🛑 Limite diário de trades atingido.")
            time.sleep(600)
            continue

        # horário
        #if now < 5 or now >= 21:
        if False:

            if not last_outside_log:
                print("⏰ Fora do horário operacional (05h-20h).")
                last_outside_log = True

            time.sleep(300)
            continue

        else:
            last_outside_log = False

        # 🔎 procurar oportunidades
        if current_trader is None:
            
            current_trader = BinanceTraderBot(
                stock_code="BTC",
                operation_code="BTCUSDT",
                traded_quantity=config["stocks_traded_list"][0]["capital"],
                traded_percentage=100,
                candle_period=CANDLE_PERIOD,
                api_key=API_KEY,
                api_secret=API_SECRET,
                config=config,
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

            symbols = scan_market_top_symbols(BINANCE_CLIENT, limit=3)
            
            if not symbols:
                print("⚠️ Nenhuma oportunidade encontrada.")
                time.sleep(20)
                continue

            for symbol in symbols:

                # evitar moedas com loss recente
                if symbol in MARKET_MEMORY:

                    last_loss = MARKET_MEMORY.get(symbol, {}).get("last_loss", 0)

                    if time.time() - last_loss < LOSS_COOLDOWN:
                        print(f"⚠️ {symbol} ignorado por loss recente")
                        continue

                now_ts = time.time()

                if symbol in symbol_cooldown and now_ts - symbol_cooldown[symbol] < COOLDOWN_SECONDS:
                    continue

                if symbol == last_traded_symbol and now_ts - symbol_cooldown.get(symbol, 0) < COOLDOWN_SECONDS:
                    continue

                stock = symbol.replace("USDT", "")

                print(f"🎯 Testando ativo: {symbol}")

                try:
                    account = safe_binance_call(BINANCE_CLIENT.get_account)
                    
                    if not account:
                        continue

                    balance = 0

                    for asset in account["balances"]:
                        if asset["asset"] == "USDT":
                            balance = float(asset["free"])
                            break

                    max_position = balance * config["RISK"]["MAX_POSITION_PERCENT"]

                    capital_config = next(
                        (s["capital"] for s in config["stocks_traded_list"]
                        if s["operationCode"] == symbol),
                        None
                    )

                    if capital_config is None:
                        continue
                    
                    capital = min(capital_config, max_position)

                    # 🔁 troca o ativo do robô
                    current_trader.stock_code = stock
                    current_trader.operation_code = symbol
                    current_trader.traded_quantity = capital

                    # resetar estado
                    current_trader.resetForNewSymbol()

                    # atualizar filtros da Binance
                    current_trader.setStepSizeAndTickSize()
                        
                    if not current_trader.updateAllData():
                        continue

                    decision = current_trader.getFinalDecisionStrategy()
                    
                    print("🔎 Decisão da estratégia:", decision)
                    
                    decision_str = str(decision).upper()

                    print(f"🔎 Decisão da estratégia: {decision_str}")

                    if decision_str in ["TRUE", "BUY", "COMPRAR"]:

                        print(f"🚀 Oportunidade encontrada em {symbol}")

                        symbol_cooldown[symbol] = time.time()
                        last_traded_symbol = symbol
                        break

                except Exception as e:
                    print(f"Erro ao analisar {symbol}: {e}")

        # executar trader
        if current_trader:

            CURRENT_TRADER = current_trader
            BINANCE_CLIENT = current_trader.client_binance

            current_trader.execute()

            if not current_trader.actual_trade_position and not last_trade_logged:

                print("⚠️ Nenhuma posição aberta. Aplicando cooldown...")

                if last_traded_symbol:
                    symbol_cooldown[last_traded_symbol] = time.time()

                entry = getattr(current_trader, "last_buy_price", 0)
                exit_price = getattr(current_trader, "last_sell_price", 0)
                qty = getattr(current_trader, "last_stock_account_balance", 0)

                if entry and exit_price and qty:
                    profit = (exit_price - entry) * qty
                else:
                    profit = 0

                last_trade_logged = True

                TRADE_HISTORY.append({
                    "time": datetime.now(br_tz).strftime("%H:%M:%S"),
                    "symbol": current_trader.operation_code,
                    "side": "SELL",
                    "entry": round(entry, 2),
                    "exit": round(exit_price, 2),
                    "profit": round(profit, 4)
                })

                update_market_memory(current_trader.operation_code, profit)

                current_trader = None
                last_traded_symbol = None
                
                time.sleep(15)

        cooldown = max(15, TEMPO_ENTRE_TRADES)
        sleep_time = max(10, cooldown)
        time.sleep(sleep_time)

    print("🛑 Loop do robô finalizado.")

def safe_trader_master_loop():
    global BOT_RUNNING

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

def calculateSmartScore(closes, volumes, highs, lows, price_change):

    try:
        
        int_cfg = config["INTELLIGENCE"]

        MOMENTUM_MULTIPLIER = int_cfg["MOMENTUM_MULTIPLIER"]
        TREND_STRENGTH_MULTIPLIER = int_cfg["TREND_STRENGTH_MULTIPLIER"]

        if len(closes) < 30:
            return 0

        # momentum
        momentum = (closes[-1] - closes[-6]) / max(closes[-6], 0.00000001)

        # volume spike
        avg_volume = sum(volumes[-20:]) / len(volumes[-20:])
        volume_score = volumes[-1] / max(avg_volume, 1)

        # volatilidade
        max_price = max(highs[-20:])
        min_price = min(lows[-20:])
        volatility = (max_price - min_price) / max(min_price, 0.0000001)

        # tendência
        ma7 = sum(closes[-7:]) / 7
        ma25 = sum(closes[-25:]) / 25

        trend_strength = abs(ma7 - ma25) / max(ma25, 0.0000001)

        score = (
            abs(momentum) * MOMENTUM_MULTIPLIER +
            volume_score * 25 +
            volatility * 20 +
            trend_strength * TREND_STRENGTH_MULTIPLIER +
            min(abs(price_change), 10)
        )

        return score

    except:
        return 0
    
def detectInstitutionalAccumulation(closes, volumes, highs, lows):

        try:

            if len(closes) < 30:
                return False

            # compressão de preço
            price_range = (
                max(closes[-20:]) - min(closes[-20:])
            ) / max(min(closes[-20:]), 0.0000001)

            compression = price_range < 0.001

            # crescimento de volume
            avg_volume = sum(volumes[-25:-5]) / 20
            recent_volume = sum(volumes[-5:]) / 5

            volume_growth = recent_volume > avg_volume * 1.4

            # volatilidade
            atr = sum([h - l for h, l in zip(highs[-14:], lows[-14:])]) / 14
            atr_pct = atr / closes[-1]

            low_volatility = atr_pct < 0.004

            if compression and volume_growth and low_volatility:

                print("🏦 ACUMULAÇÃO INSTITUCIONAL DETECTADA")

                return True

            return False

        except:
            return False    

def detectExplosionSignal(closes, volumes, highs, lows):

    try:

        if len(closes) < 25:
            return False

        # compressão de preço
        price_range = (
            max(closes[-15:]) - min(closes[-15:])
        ) / max(min(closes[-15:]), 0.0000001)

        compression = price_range < 0.012

        # aceleração de volume
        avg_volume = sum(volumes[-20:]) / len(volumes[-20:])
        recent_volume = sum(volumes[-3:]) / 3

        volume_acceleration = recent_volume > avg_volume * 1.8

        # momentum positivo
        momentum = (closes[-1] - closes[-4]) / max(closes[-4], 0.0000001)

        breakout_pressure = momentum > 0.003

        if compression and volume_acceleration and breakout_pressure:

            print("🚀 POSSÍVEL EXPLOSÃO DETECTADA")

            return True

        return False

    except:
        return False
    
def detectSmartMoney(closes, volumes, highs, lows, imbalance):

    try:

        if len(closes) < 30:
            return False

        # compressão de preço
        price_range = (
            max(closes[-20:]) - min(closes[-20:])
        ) / max(min(closes[-20:]), 0.0000001)

        compression = price_range < 0.006

        # aumento de volume recente
        avg_volume = sum(volumes[-25:-5]) / 20
        recent_volume = sum(volumes[-5:]) / 5

        volume_growth = recent_volume > avg_volume * 1.3

        # pressão de compra institucional
        whale_buying = imbalance > 1.5

        if compression and volume_growth and whale_buying:

            print("🏦 SMART MONEY DETECTADO")

            return True

        return False

    except:
        return False

def analyze_symbol(client, t, config):
    
    int_cfg = config["INTELLIGENCE"]
    WHALE_IMBALANCE = int_cfg["WHALE_IMBALANCE"]
    
    scanner_cfg = config["SCANNER"]

    MIN_VOLATILITY = scanner_cfg["MIN_VOLATILITY"]
    MAX_VOLATILITY = scanner_cfg["MAX_VOLATILITY"]
    
    SPREAD_LIMIT = scanner_cfg["SPREAD_LIMIT"]
    
    try:

        symbol = t["symbol"]
        volume = float(t["quoteVolume"])
        price_change = float(t.get("priceChangePercent", 0))
        
        # ignora moedas paradas
        if abs(price_change) < 0.2:
            return None
        
        if abs(price_change) > config["SCANNER"]["PUMP_PROTECTION"] * 100:
            return None
        
        # 🔎 filtro de spread do orderbook
        global ORDERBOOK_CACHE, ORDERBOOK_CACHE_TIME

        now = time.time()

        if now - ORDERBOOK_CACHE_TIME > 5:
            ORDERBOOK_CACHE = {}
            ORDERBOOK_CACHE_TIME = now

        if symbol not in ORDERBOOK_CACHE:
            ORDERBOOK_CACHE[symbol] = safe_binance_call(
                client.get_order_book,
                symbol=symbol,
                limit=5
            )

        book = ORDERBOOK_CACHE.get(symbol)
        
        if not book:
            return None

        if not book.get("bids") or not book.get("asks"):
            return None

        bid = float(book["bids"][0][0])
        ask = float(book["asks"][0][0])

        spread = (ask - bid) / bid

        bid_vol = sum(float(b[1]) for b in book["bids"][:5])
        ask_vol = sum(float(a[1]) for a in book["asks"][:5])

        imbalance = bid_vol / max(ask_vol, 1)

        if imbalance < WHALE_IMBALANCE:
            return None

        # ignora moedas com spread alto
        #if spread > 0.002:   # 0.2%
        #   return None 
        
        if spread > SPREAD_LIMIT:
            return None

        candles = safe_binance_call(
            client.get_klines,
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_5MINUTE,
            limit=50
        )

        if not candles:
            return None

        closes = [float(c[4]) for c in candles]
        volumes = [float(c[5]) for c in candles]
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]

        # calcular volatilidade
        max_price = max(highs[-20:])
        min_price = min(lows[-20:])

        if min_price == 0:
            return None

        volatility = (max_price - min_price) / min_price
        
        if volatility < MIN_VOLATILITY:
            return None

        if volatility > MAX_VOLATILITY:
            return None

        if len(closes) < 30:
            return None

        momentum = (closes[-1] - closes[-5]) / max(closes[-5], 0.0000001)

        smart_score = calculateSmartScore(
            closes,
            volumes,
            highs,
            lows,
            price_change
        )

        accumulation_signal = detectInstitutionalAccumulation(
            closes,
            volumes,
            highs,
            lows
        )

        volume_weight = min(volume / 10000000, 5)

        smart_money_signal = detectSmartMoney(
            closes,
            volumes,
            highs,
            lows,
            imbalance
        )

        score = smart_score * (1 + volume_weight)

        if accumulation_signal:
            score *= 1.4

        if smart_money_signal:
            score *= 1.8
            
        if smart_money_signal and symbol not in SCANNER_SMART_MONEY:
            SCANNER_SMART_MONEY.append(symbol)

        return {
            "symbol": symbol,
            "score": score,
            "momentum": momentum,
            "volume": volume
        }

    except Exception as e:

        logging.error(f"Erro analisando {t.get('symbol','UNKNOWN')}: {e}")
        return None

def analyze_symbol_wrapper(t):

    try:
        return analyze_symbol(BINANCE_CLIENT, t, config)

    except Exception as e:

        print(f"Erro ao analisar {t}: {e}")
        return None

LAST_SCAN = 0
SCAN_CACHE = []

ORDERBOOK_CACHE = {}
ORDERBOOK_CACHE_TIME = 0

def scan_market_top_symbols(client, limit=10):

    global LAST_SCAN, SCAN_CACHE, SCANNER_SMART_MONEY, SCANNER_RANKING

    if time.time() - LAST_SCAN < 30 and SCAN_CACHE:
        return SCAN_CACHE

    start_scan_time = time.time()

    SCANNER_SMART_MONEY.clear()
    SCANNER_RANKING.clear()

    print("🔎 Escaneando mercado inteligente PRO...")

    try:

        tickers = safe_binance_call(client.get_ticker)

        if not tickers:
            return []

        STABLE_FILTER = {
            "USDCUSDT","FDUSDUSDT","TUSDUSDT",
            "BUSDUSDT","USDPUSDT","RLUSDUSDT",
            "PAXGUSDT","XAUTUSDT"
        }

        # filtro inicial rápido
        MIN_VOLUME = config["SCANNER"]["MIN_VOLUME"]
                
        filtered = []

        for t in tickers:

            symbol = t["symbol"]

            if not symbol.endswith("USDT"):
                continue

            if symbol in STABLE_FILTER or symbol.startswith(("USDC","TUSD","FDUSD","USDP")):
                continue
            
            if "UPUSDT" in symbol or "DOWNUSDT" in symbol:
                continue   
                       
            volume = float(t.get("quoteVolume",0))
            trades = int(t.get("count",0))

            if volume < MIN_VOLUME:
                continue

            if trades < config["SCANNER"]["MIN_TRADES"]:
                continue

            change = abs(float(t.get("priceChangePercent",0)))

            score = volume * (1 + change / 100)

            filtered.append((t, score))   # guarda ticker inteiro

        if not filtered:
            return []

        filtered.sort(key=lambda x: x[1], reverse=True)
        
        SCAN_LIMIT = config["SCANNER"]["SCAN_LIMIT"]

        filtered = filtered[:SCAN_LIMIT]

        # pegar top 30
        symbols = [t for t, _ in filtered[:SCAN_LIMIT]]

        # análise paralela
        max_workers = min(8, os.cpu_count() or 1)
            
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(analyze_symbol_wrapper, symbols))

        candidates = [
            r for r in results
            if r and r["score"] > 2.5
        ]

        candidates.sort(key=lambda x: x["score"], reverse=True)

        if not candidates:
            return []

        SCANNER_RANKING[:] = [
            (c["symbol"], c["score"], c["momentum"], c["volume"])
            for c in candidates[:10]
        ]

        best = [c["symbol"] for c in candidates[:limit]]

        print("🔥 TOP OPORTUNIDADES:", best)
        print(f"⏱️ Scan completo em {time.time() - start_scan_time:.2f}s")

        SCAN_CACHE = best
        LAST_SCAN = time.time()

        return best

    except Exception as e:

        print("Erro no scanner:", e)
        return []   
             
    
               
# Inicia o robô principal
if __name__ == "__main__":
    print("🤖 Master Trader iniciado (modo multi-moedas inteligente).")

    BOT_RUNNING = True

    bot_thread = threading.Thread(
        target=safe_trader_master_loop,
        daemon=True
    )

    bot_thread.start()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        BOT_RUNNING = False
        print("🛑 Robô encerrado pelo usuário.")            
    
def update_market_memory(symbol, profit):

    now = time.time()

    if symbol not in MARKET_MEMORY:
        MARKET_MEMORY[symbol] = {
            "wins": 0,
            "losses": 0,
            "last_loss": 0
        }

    if profit > 0:
        MARKET_MEMORY[symbol]["wins"] += 1
    else:
        MARKET_MEMORY[symbol]["losses"] += 1
        MARKET_MEMORY[symbol]["last_loss"] = now
    
    # -----------------------------
    # ADAPTIVE WEIGHT UPDATE

    if profit > 0:
        ADAPTIVE_WEIGHTS["pre_pump"] = min(5, ADAPTIVE_WEIGHTS["pre_pump"] * 1.02)
        ADAPTIVE_WEIGHTS["squeeze"] = min(4, ADAPTIVE_WEIGHTS["squeeze"] * 1.01)
        ADAPTIVE_WEIGHTS["orderflow"] = min(4, ADAPTIVE_WEIGHTS["orderflow"] * 1.02)
        ADAPTIVE_WEIGHTS["sweep"] = min(4, ADAPTIVE_WEIGHTS["sweep"] * 1.01)
    else:
        ADAPTIVE_WEIGHTS["pre_pump"] = max(1.5, ADAPTIVE_WEIGHTS["pre_pump"] * 0.98)
        ADAPTIVE_WEIGHTS["squeeze"] = max(1.2, ADAPTIVE_WEIGHTS["squeeze"] * 0.99)
        ADAPTIVE_WEIGHTS["orderflow"] = max(1.2, ADAPTIVE_WEIGHTS["orderflow"] * 0.98)
        ADAPTIVE_WEIGHTS["sweep"] = max(1.2, ADAPTIVE_WEIGHTS["sweep"] * 0.99)
        
    logging.info(f"Adaptive weights updated: {ADAPTIVE_WEIGHTS}")