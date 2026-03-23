import os
import json
import time
import random
import logging
import threading
import asyncio
from src.utils.websocket_price import start_socket

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

# -----------------------------------------
# ⚙️ CONFIG

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "app", "config.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)
    
def update_equity(balance, pnl):
    equity = balance + pnl

    STATE["equity"] = equity
    
def log_trade(symbol, profit):

    STATE["trades"].append({
        "symbol": symbol,
        "profit": profit,
        "time": time.time()
    })

    # limita memória
    if len(STATE["trades"]) > 500:
        STATE["trades"].pop(0)
        
def run_socket():
    asyncio.run(start_socket())

threading.Thread(target=run_socket, daemon=True).start()

config = load_config()

# -----------------------------------------
# 🔧 GLOBAIS IMPORTANTES

risk_manager = RiskManager(config)

price_stream = PriceStream(API_KEY, API_SECRET)
price_stream.start("BTCUSDT")

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
cached_symbols = []

def get_best_symbol():

    data = scan_market_pro(client)

    if not data:
        return None

    ranking = data.get("ranking", [])

    if not ranking:
        print("⚠️ Nenhum ativo encontrado")
        return None

    symbol = ranking[0].get("symbol")

    print(f"🎯 Melhor ativo: {symbol}")

    return symbol

# -----------------------------------------
# 🤖 BOT

def create_bot():
    client = get_client()

    bot = BinanceTraderBot(
        symbol="BTCUSDT",
        client=client,
        config=config,
        risk_manager=risk_manager
    )

    bot.price_stream = price_stream
    bot.is_running = True  # 🔥 ESSENCIAL

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
            engine.run_once()
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

        BOT_RUNNING = True  # 🔥 SÓ AQUI

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
    start_bot()
    safe_trader_master_loop()