import os
import json
import time
import random
import logging
import threading
import asyncio
from src.utils.websocket_price import start_socket

from src.config.settings import load_config

from src.utils.state_manager import StateManager

from dotenv import load_dotenv
from binance.client import Client
from src.state import STATE

from src.core.engine import TradingEngine
from src.core.decision import DecisionEngine
from src.strategies.strategy_runner import StrategyRunner
from src.exchange.BinanceTraderBot import BinanceTraderBot
from src.scanner.market_scanner_pro import scan_market_pro
from src.core.risk_manager import RiskManager
from src.exchange.price_stream import PriceStream
from src.utils.report import generate_report
from src.data.data_provider import get_klines

# -----------------------------------------
# 🔐 ENV

# 📁 caminho absoluto correto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "..", "logs")

os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "trading_bot.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BOT_RUNNING = False
CURRENT_TRADER = None

config = load_config()
MAX_TRADES_PER_DAY = config.get("MAX_TRADES_PER_DAY", 10)
state = StateManager()

# -----------------------------------------
# ⚙️ CONFIG

TRADE_HISTORY = []

def add_trade(trade):
    TRADE_HISTORY.append(trade)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "app", "config.json")
    
def update_equity(balance, pnl):
    equity = balance + pnl

    STATE["equity"] = equity
    
def run_socket():
    asyncio.run(start_socket())

# -----------------------------------------
# 🔧 GLOBAIS IMPORTANTES

risk_manager = RiskManager(config)

client = None
engine = None

# -----------------------------------------
# 🚀 CLIENT

def get_client():
    global client

    if client is None:
        client = Client(API_KEY, API_SECRET)

    return client

# -----------------------------------------
# 🔍 SCANNER

last_scan = 0
cached_symbols = None

def get_best_symbol():
    global last_scan, cached_symbol

    client_local = get_client()

    if time.time() - last_scan < 60:
        return cached_symbol

    data = scan_market_pro(client_local)

    if not data:
        return cached_symbol

    ranking = data.get("ranking", [])[:10]

    best_symbol = None
    best_score = 0

    for coin in ranking:
        symbol = coin.get("symbol")

        try:
            df = get_klines(client_local, symbol)

            if df is None or df.empty or len(df) < 50:
                continue

            # -----------------------------------------
            # 🧠 FILTROS PROFISSIONAIS

            price = df["close"].iloc[-1]

            # volatilidade
            volatility = df["close"].pct_change().rolling(10).std().iloc[-1]

            if volatility is None:
                continue

            if volatility < 0.002 or volatility > 0.03:
                continue

            # volume
            volume = df["volume"].iloc[-1]
            avg_volume = df["volume"].rolling(20).mean().iloc[-1]

            volume_score = 1 if volume > avg_volume else 0

            # tendência
            ma20 = df["close"].rolling(20).mean().iloc[-1]
            ma50 = df["close"].rolling(50).mean().iloc[-1]

            trend_score = 1 if ma20 > ma50 else 0

            # momentum
            momentum = (df["close"].iloc[-1] - df["close"].iloc[-5]) / df["close"].iloc[-5]
            momentum_score = 1 if momentum > 0 else 0

            # -----------------------------------------
            # 🔥 SCORE FINAL

            score = (
                (volatility * 10) +      # movimento
                (volume_score * 0.5) +
                (trend_score * 0.7) +
                (momentum_score * 0.8)
            )

            print(f"📊 {symbol} | score={score:.3f}")

            if score > best_score:
                best_score = score
                best_symbol = symbol

        except Exception as e:
            print(f"Erro no scanner {symbol}: {e}")
            continue

    if best_symbol:
        print(f"🎯 Melhor ativo selecionado: {best_symbol} | score={best_score:.3f}")
        cached_symbol = best_symbol
        last_scan = time.time()
        return best_symbol

    return cached_symbol

# -----------------------------------------
# 🤖 BOT

def create_bot():
    client = get_client()

    price_stream = PriceStream(API_KEY, API_SECRET)
    price_stream.start("BTCUSDT")

    bot = BinanceTraderBot(
        symbol="BTCUSDT",
        client=client,
        config=config,
        risk_manager=risk_manager
    )

    bot.price_stream = price_stream
    bot.is_running = True

    return bot

# -----------------------------------------
# 🧠 COMPONENTES

strategy_runner = StrategyRunner()
decision_engine = DecisionEngine(config)

# -----------------------------------------
# 🔁 LOOP

def safe_trader_master_loop():
    global BOT_RUNNING, CURRENT_TRADER, engine

    print("🔥 LOOP ATIVO")

    while True:

        if not BOT_RUNNING or not engine or not CURRENT_TRADER or not CURRENT_TRADER.is_running:
            time.sleep(5)
            continue

        try:
            print("🚀 Novo ciclo")

            # 🔄 RESET DIÁRIO
            state.check_reset()

            # 🛑 LIMITE DE TRADES
            if not state.can_trade(MAX_TRADES_PER_DAY):
                time.sleep(10)
                continue

            # 🧠 EXECUÇÃO
            engine.run_once()

            print(f"📊 Trades hoje: {state.trades_today}")

            try:
                balance = CURRENT_TRADER.get_balance()
                pnl = CURRENT_TRADER.get_pnl()
                update_equity(balance, pnl)
            except:
                pass

            time.sleep(5 + random.uniform(1, 3))

        except Exception as e:
            import traceback
            print("❌ ERRO NO BOT:", e)
            traceback.print_exc()
            time.sleep(3)
            
# -----------------------------------------
# ▶️ START

def start_bot():
    global BOT_RUNNING, CURRENT_TRADER, engine

    if BOT_RUNNING:
        print("⚠️ Já está rodando")
        return

    print("🚀 Iniciando bot...")

    try:
        bot = create_bot()
        CURRENT_TRADER = bot

        engine = TradingEngine(
            bot=bot,
            scanner=get_best_symbol,
            strategy_runner=strategy_runner,
            decision_engine=decision_engine,
            config=config,
            risk_manager=risk_manager
        )

        BOT_RUNNING = True

        print("✅ Bot iniciado com sucesso")

    except Exception as e:
        print("❌ ERRO:", e)
        BOT_RUNNING = False
        
# -----------------------------------------
# ⛔ STOP

def stop_bot():
    global BOT_RUNNING, CURRENT_TRADER

    print("🛑 Parando bot...")

    BOT_RUNNING = False

    if CURRENT_TRADER:
        CURRENT_TRADER.is_running = False

# -----------------------------------------

if __name__ == "__main__":
    print("🧠 Loop do bot iniciado em background")
    
    threading.Thread(target=run_socket, daemon=True).start()
    
    start_bot()
    safe_trader_master_loop()