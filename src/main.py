import os
import json
import time
from dotenv import load_dotenv
from binance.client import Client

from src.core.engine import TradingEngine
from src.core.decision import DecisionEngine
from src.strategies.strategy_runner import StrategyRunner
from src.exchange.BinanceTraderBot import BinanceTraderBot
from src.scanner.market_scanner_pro import scan_market_pro

from src.core.risk_manager import RiskManager

# -----------------------------------------
# 🔐 ENV

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


config = load_config()

print("API_KEY:", API_KEY[:5] if API_KEY else None)
print("API_SECRET:", API_SECRET[:5] if API_SECRET else None)

# -----------------------------------------
# 🚀 INIT CLIENT

client = Client(API_KEY, API_SECRET)

risk_manager = RiskManager(config)


# -----------------------------------------
# 🧠 COMPONENTES

strategy_runner = StrategyRunner()
decision_engine = DecisionEngine(config)

# -----------------------------------------
# 🔍 SCANNER (cache simples)

last_scan = 0
cached_symbols = []

def create_bot():

    return BinanceTraderBot(
        symbol="BTCUSDT",
        client=client,
        config=config,
        risk_manager=risk_manager
    )

def get_best_symbol():
    global last_scan, cached_symbols

    if time.time() - last_scan > 20:
        try:
            cached_symbols = scan_market_pro(client)
            last_scan = time.time()
        except Exception as e:
            print("⚠️ Erro no scanner:", e)
            return None

    return cached_symbols[0] if cached_symbols else None

# -----------------------------------------
# 🧠 COMPONENTES
strategy_runner = StrategyRunner()
decision_engine = DecisionEngine(config)

# -----------------------------------------
# ⚙️ ENGINE

engine = None

# -----------------------------------------
# ▶️ START SEGURO

def safe_trader_master_loop():

    global BOT_RUNNING, CURRENT_TRADER, engine

    print("🔥 LOOP ATIVO")

    while True:

        if not BOT_RUNNING or not engine:
            time.sleep(1)
            continue

        try:
            engine.run_once()

        except Exception as e:
            print("❌ ERRO NO BOT:", e)

        time.sleep(2)
        
def start_bot():

    global BOT_RUNNING, CURRENT_TRADER, engine

    print("🚀 Iniciando bot...")

    print("👉 criando bot...")
    bot = create_bot()
    print("✅ bot criado")

    CURRENT_TRADER = bot

    print("👉 criando engine...")
    engine = TradingEngine(...)
    print("✅ engine criado")

    BOT_RUNNING = True
    print("🔥 BOT_RUNNING TRUE")
    
def stop_bot():

    global BOT_RUNNING, CURRENT_TRADER

    print("🛑 Parando bot...")

    if CURRENT_TRADER:
        CURRENT_TRADER.is_running = False

