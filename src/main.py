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

from src.utils.market_mode import detect_market_mode

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

MARKET_MEMORY = {}
LOSS_COOLDOWN = 3600  # 1 hora

ADAPTIVE_WEIGHTS = {
    "pre_pump": 3.0,
    "squeeze": 2.0,
    "orderflow": 2.0,
    "sweep": 2.0
}

BINANCE_CLIENT = None

symbol_cooldown = {}
COOLDOWN_SECONDS = 1800  # 30 minutos

MAX_TRADES_PER_DAY = 20

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


# 🔴🔴🔴 CONFIGURAÇÕES - FIM 🔴🔴🔴
# -------------------------------------------------------------------------------------------------

last_traded_symbol = None

# 🔁 LOOP PRINCIPAL
# 🔁 LOOP PRINCIPAL INTELIGENTE (UMA MOEDA POR VEZ)

thread_lock = threading.Lock()


def trader_master_loop():
    global CURRENT_TRADER, BOT_RUNNING, BINANCE_CLIENT, last_traded_symbol

    current_trader = None
    last_outside_log = False
        
    try:
        if BINANCE_CLIENT is None:
            BINANCE_CLIENT = Client(API_KEY, API_SECRET)

    except Exception as e:
        print("Erro conectando Binance:", e)
        time.sleep(10)
        return
    
    while BOT_RUNNING:
        
        # limpeza da memória
        if len(MARKET_MEMORY) > 200:
            MARKET_MEMORY.clear()
        
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

        # Limite diário
        if len(TRADE_HISTORY) >= MAX_TRADES_PER_DAY:
            print("🛑 Limite diário de trades atingido.")
            time.sleep(600)
            continue
        
        if now < 5 or now >= 21:
            if not last_outside_log:
                print("⏰ Fora do horário operacional (05h-20h). Aguardando...")
                last_outside_log = True
            time.sleep(300)
            continue   
                    
        else:
            last_outside_log = False

        if current_trader is None:

            print("🔎 Procurando melhor oportunidade...")

            symbols = scan_market_top_symbols(BINANCE_CLIENT, limit=12)
            
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
                
                # 🔒 Evita repetir o mesmo ativo
                if symbol == last_traded_symbol:
                    continue    
                
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

                    if not trader.updateAllData():
                        continue

                    decision = trader.getFinalDecisionStrategy()

                    # normalizar decisão
                    decision_str = str(decision).upper()
                    
                    print(f"🔎 Decisão da estratégia: {decision_str}")

                    if decision_str in ["TRUE", "BUY", "COMPRAR"]:
                        print(f"🚀 Oportunidade encontrada em {symbol}")
                        symbol_cooldown[symbol] = time.time()
                        last_traded_symbol = symbol
                        current_trader = trader
                        break

                except Exception as e:
                    print(f"Erro ao analisar {symbol}: {e}")

        # Limite diário de trades
        if len(TRADE_HISTORY) >= MAX_TRADES_PER_DAY:
            print("🛑 Limite diário de trades atingido.")
            time.sleep(600)
            continue   

        if current_trader:
            CURRENT_TRADER = current_trader
            BINANCE_CLIENT = current_trader.client_binance
            current_trader.execute()

            if not current_trader.actual_trade_position:

                print("⚠️ Nenhuma posição aberta. Aplicando cooldown...")

                symbol_cooldown[last_traded_symbol] = time.time()

                if hasattr(current_trader, "last_trade_profit"):

                    profit = current_trader.last_trade_profit

                    TRADE_HISTORY.append({
                        "timestamp": time.time(),
                        "asset": current_trader.operation_code,
                        "profit": profit
                    })

                    update_market_memory(current_trader.operation_code, profit)

                current_trader = None
                last_traded_symbol = None
                
                time.sleep(15)
        
        # 🔥 sleep global do loop        
        cooldown = max(15, TEMPO_ENTRE_TRADES)
        time.sleep(cooldown)

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

def scan_market_top_symbols(client, limit=10):

    print("🔎 Escaneando mercado inteligente PRO...")

    try:

        tickers = client.get_ticker()

        # manter apenas pares USDT
        tickers = [t for t in tickers if t["symbol"].endswith("USDT")]
        
        if not tickers:
            return []

        # 🔥 Ordena por volume e pega apenas top 80
        tickers = sorted(
            tickers,
            key=lambda x: float(x.get("quoteVolume", 0)),
            reverse=True
        )[:120]

        if not tickers:
            return []

        candidates = []
        
        market_mode_global = None
        market_mode = None
        

        for t in tickers:
            
            symbol = t["symbol"]
            volume = float(t.get("quoteVolume", 0))
            trade_count = int(t.get("count", 0))

            print("SCAN:", symbol, volume, trade_count)

            symbol = t["symbol"]

            if not symbol.endswith("USDT"):
                continue
            
            # 🚫 Ignorar stablecoins e pares sintéticos
            if symbol.startswith(("USDC","FDUSD","EUR","USD","RLUSD")):
                continue    
            # 🚫 Ignorar tokens alavancados
            if symbol.endswith(("UPUSDT","DOWNUSDT","BULLUSDT","BEARUSDT")):
                continue    

            volume = float(t["quoteVolume"])
            
            trade_count = int(t.get("count", 0))

            if trade_count < 50:
                continue
            
            price_change = float(t.get("priceChangePercent", 0))

            price = float(t.get("lastPrice", 0))

            bid = float(t.get("bidPrice", 0))
            ask = float(t.get("askPrice", 0))

            if bid > 0 and ask > 0:
                spread = (ask - bid) / bid
                if spread > 0.004:
                    continue

            if price == 0:
                continue

            # filtro de liquidez
            if volume < 1_000_000:
                continue

            try:

                candles = client.get_klines(
                    symbol=symbol,
                    interval=Client.KLINE_INTERVAL_5MINUTE,
                    limit=30
                )
                
                time.sleep(0.05)

                closes = [float(c[4]) for c in candles]
                volumes = [float(c[5]) for c in candles]
                avg_volume = sum(volumes[-20:]) / max(len(volumes[-20:]),1)
                current_volume = volumes[-1]
                highs = [float(c[2]) for c in candles]
                lows = [float(c[3]) for c in candles]

                # -----------------------------
                # MARKET MODE DETECTOR

                market_mode = detect_market_mode(volumes)

                # se mercado estiver com liquidez muito baixa ignora
                if market_mode == "LOW_ACTIVITY":
                    pass

                # se estiver baixa liquidez reduz score depois
                low_liquidity_mode = market_mode == "LOW_LIQUIDITY"

                # -----------------------------
                # ORDER FLOW ACCELERATION

                volume_recent = sum(volumes[-5:]) / max(len(volumes[-5:]),1)
                volume_previous = sum(volumes[-10:-5]) / max(len(volumes[-10:-5]),1)

                if volume_previous == 0:
                    volume_acceleration = 0
                else:
                    volume_acceleration = volume_recent / volume_previous

                orderflow_signal = volume_acceleration > 1.6

                if len(closes) < 20:
                    continue

                min_price = min(lows)
                max_price = max(highs)

                if min_price == 0:
                    continue
                # evita moedas ultrabaratas    
                if min_price < 0.0000005:
                    continue

                volatility = (max_price - min_price) / min_price
                
                #print(symbol, "volume:", volume, "vol:", volatility)
                print(f"{symbol} | volume={volume:,.0f} | vol={volatility:.4f} | trades={trade_count}")
                
                if volatility > 0.25:
                    continue

                # média curta
                ma7 = sum(closes[-7:]) / 7

                # média longa
                ma25 = sum(closes[-25:]) / 25

                trend_strength = (ma7 - ma25) / ma25
                
                # -----------------------------
                # -----------------------------
                # VOLATILITY SQUEEZE (Bollinger)

                if len(closes) < 20 or closes[-1] == 0:
                    squeeze_signal = False
                else:
                    std_dev = statistics.stdev(closes[-20:])
                    bollinger_width = (std_dev * 2) / closes[-1]
                    squeeze_signal = bollinger_width < 0.008
                
                accumulation_signal = (
                    volatility < 0.02 and
                    volume_recent > avg_volume * 1.3
                )
                
                # -----------------------------
                # DETECTOR DE PRÉ-PUMP

                recent_range = (max(closes[-10:]) - min(closes[-10:])) / min(closes[-10:])

                volume_spike = current_volume > avg_volume * 1.8

                pre_pump_signal = (
                    recent_range < 0.015 and
                    volume_spike and
                    len(closes) >= 3 and closes[-1] > closes[-3]
                )

                # evita moedas lateralizadas
                if volatility < 0.002:
                    continue

                # evita pump exagerado
                if abs(price_change) > 20:
                    continue

                if closes[-5] == 0:
                    continue

                momentum = (closes[-1] - closes[-5]) / max(closes[-5], 0.00000001) 
                 
                dump_risk = (closes[-1] - closes[-3]) / max(closes[-3], 0.00000001)

                #if dump_risk < -0.04:
                #    continue
                
                # -----------------------------
                # LIQUIDITY SWEEP DETECTOR

                recent_low = min(lows[-5:])
                previous_low = min(lows[-15:-5])

                recent_high = max(highs[-5:])
                previous_high = max(highs[-15:-5])

                sweep_down = recent_low < previous_low and closes[-1] > previous_low
                sweep_up = recent_high > previous_high and closes[-1] < previous_high

                liquidity_sweep_signal = sweep_down or sweep_up  

                #if closes[-1] > max(closes[-10:]) * 1.15:
                #    continue

                score = (
                    math.log(max(volume,1)) *
                    (volatility ** 0.7) *
                    abs(trend_strength) *
                    abs(price_change) *
                    abs(momentum) *
                    (ADAPTIVE_WEIGHTS["pre_pump"] if pre_pump_signal else 1) *
                    (ADAPTIVE_WEIGHTS["squeeze"] if squeeze_signal else 1) *
                    (ADAPTIVE_WEIGHTS["orderflow"] if orderflow_signal else 1) *
                    (ADAPTIVE_WEIGHTS["sweep"] if liquidity_sweep_signal else 1)
                )
                
                # ajuste baseado no modo de mercado
                if market_mode == "HIGH_VOLATILITY":
                    score *= 1.2

                if low_liquidity_mode:
                    score *= 0.7
                
                score *= (1.5 if accumulation_signal else 1)
                
                # bônus de win rate
                if symbol in MARKET_MEMORY:

                    wins = MARKET_MEMORY[symbol]["wins"]
                    losses = MARKET_MEMORY[symbol]["losses"]

                    total = wins + losses

                    if total >= 3:
                        winrate = wins / total
                        score *= (1 + winrate)
                        
                candidates.append((symbol, score))

            except Exception:
                continue

        candidates.sort(key=lambda x: x[1], reverse=True)

        best = [s[0] for s in candidates[:limit]]

        print("🔥 TOP OPORTUNIDADES:", best)

        time.sleep(2)

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