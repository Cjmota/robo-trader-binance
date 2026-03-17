import os
import json
import time
from dotenv import load_dotenv

from binance.client import Client

from src.core.engine import TradingEngine
from src.core.decision import DecisionEngine
from src.strategies.StrategyRunner import StrategyRunner
from src.exchange.BinanceTraderBot import BinanceTraderBot

from src.scanner.market_scanner_pro import scan_market_pro

# -----------------------------------------
# 🔐 ENV

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")

# -----------------------------------------
# ⚙️ CONFIG

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "app", "config.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

config = load_config()

# -----------------------------------------
# 🚀 INIT

client = Client(API_KEY, API_SECRET)

bot = BinanceTraderBot(
    symbol="BTCUSDT",  # inicial (vai trocar no scanner)
    client=client,
    config=config
)

strategy_runner = StrategyRunner()
decision_engine = DecisionEngine(config)

# -----------------------------------------
# 🧠 ENGINE

last_scan = 0
cached_symbols = []

def get_best_symbol():
    global last_scan, cached_symbols

    if time.time() - last_scan > 20:
        cached_symbols = scan_market_pro(client)
        last_scan = time.time()

    return cached_symbols[0] if cached_symbols else None

engine = TradingEngine(
    bot=bot,
    scanner=get_best_symbol,
    strategy_runner=strategy_runner,
    decision_engine=decision_engine,
    config=config
)

# -----------------------------------------
# ▶️ START

if __name__ == "__main__":

    print("🤖 Sistema iniciado (PRO)")

    engine.start()