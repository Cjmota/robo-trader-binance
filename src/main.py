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

logger = logging.getLogger()

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
cached_symbol = None
LAST_SYMBOL = None

def get_best_symbol():
    global last_scan, cached_symbol, LAST_SYMBOL

    client_local = get_client()

    if time.time() - last_scan < 60 and cached_symbol:
        return cached_symbol

    data = scan_market_pro(client_local)

    if not data:
        return cached_symbol

    ranking = data.get("ranking", [])[:10]

    best_symbol = ranking[0]["symbol"] if ranking else None

    if best_symbol and best_symbol != LAST_SYMBOL:
        logger.info(f"🔄 Mudando ativo: {LAST_SYMBOL} → {best_symbol}")
        LAST_SYMBOL = best_symbol

    cached_symbol = LAST_SYMBOL
    last_scan = time.time()

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

    last_cycle_log = 0

    while True:
        try:
            now = time.time()

            # 🔥 LOG CONTROLADO
            if now - last_cycle_log > 10:
                logger.info("🚀 Novo ciclo")
                last_cycle_log = now

            # 🛑 VALIDAÇÕES IMPORTANTES
            if not BOT_RUNNING or not engine or not CURRENT_TRADER or not CURRENT_TRADER.is_running:
                time.sleep(5)
                continue

            # 🔄 RESET DIÁRIO
            state.check_reset()

            # 🛑 LIMITE DE TRADES
            if not state.can_trade(MAX_TRADES_PER_DAY):
                logger.warning("⚠️ Limite diário atingido")
                time.sleep(10)
                continue

            # 🧠 EXECUÇÃO
            engine.run_once()
            time.sleep(2)

            logger.info(f"📊 Trades hoje: {state.trades_today}")

            # 💰 EQUITY
            try:
                balance = CURRENT_TRADER.get_balance()
                pnl = CURRENT_TRADER.get_pnl()
                update_equity(balance, pnl)
            except Exception as e:
                logger.debug(f"Erro ao atualizar equity: {e}")

            # ⏱️ DELAY ANTI-SPAM
            time.sleep(5 + random.uniform(1, 3))

        except Exception as e:
            logger.exception("Erro detalhado:")
            logger.error(f"❌ ERRO NO BOT: {e}")
            time.sleep(3)
                        
# -----------------------------------------
# ▶️ START

def start_bot():
    global BOT_RUNNING, CURRENT_TRADER, engine

    if BOT_RUNNING:
        logger.warning("⚠️ Já está rodando")
        return

    logger.info("🚀 Iniciando bot...")

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

        logger.info("✅ Bot iniciado com sucesso")

    except Exception as e:
        logger.error(f"❌ ERRO: {e}")
        BOT_RUNNING = False
        
# -----------------------------------------
# ⛔ STOP

def stop_bot():
    global BOT_RUNNING, CURRENT_TRADER

    logger.info("🛑 Parando bot...")

    BOT_RUNNING = False

    if CURRENT_TRADER:
        CURRENT_TRADER.is_running = False

# -----------------------------------------

if __name__ == "__main__":
    print("🧠 Loop do bot iniciado em background")
    
    threading.Thread(target=run_socket, daemon=True).start()
    
    start_bot()
    safe_trader_master_loop()