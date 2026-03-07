from flask import Flask, render_template, request, jsonify
from src.main import SCANNER_RANKING, SCANNER_SMART_MONEY
from datetime import datetime
import numpy as np
import threading
from src import main
import json
import os


EQUITY_HISTORY = []
BTC_HISTORY = []
INITIAL_EQUITY = None

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)
bot_thread = None

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app", "config.json")

# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("dashboard.html")

# ---------------- STATUS ----------------
@app.route("/status")
def status():
    trader = main.CURRENT_TRADER

    return jsonify({
        "running": main.BOT_RUNNING,
        "asset": trader.operation_code if trader else "Nenhum",
        "position": "Comprado" if trader and trader.actual_trade_position else "Vendido",
        "daily_profit": round(trader.daily_profit, 4) if trader else 0,
        "sleep_time": trader.time_to_sleep if trader else 0
    })

# ---------------- START ----------------
@app.route("/start", methods=["POST"])
def start_bot():
    global bot_thread
    if not main.BOT_RUNNING:
        main.BOT_RUNNING = True
        bot_thread = threading.Thread(target=main.safe_trader_master_loop)
        bot_thread.daemon = True
        bot_thread.start()
    return "OK"

# ---------------- STOP ----------------
@app.route("/stop", methods=["POST"])
def stop_bot():
    main.BOT_RUNNING = False
    return "OK"

# ---------------- CONFIG ----------------
@app.route("/get-config")
def get_config():
    with open(CONFIG_PATH, "r") as f:
        return jsonify(json.load(f))

@app.route("/update-config", methods=["POST"])
def update_config():
    with open(CONFIG_PATH, "w") as f:
        json.dump(request.json, f, indent=4)
    return "OK"

@app.route("/trades")
def get_trades():
    return jsonify(main.TRADE_HISTORY)

@app.route("/equity")
def equity():
    global INITIAL_EQUITY

    try:
        if not hasattr(main, "BINANCE_CLIENT") or main.BINANCE_CLIENT is None:
            return {
                "equity": 0,
                "cumulative_pct": 0,
                "max_drawdown": 0,
                "sharpe": 0,
                "btc_price": 0
            }

        account = main.BINANCE_CLIENT.get_account()

        total_usdt = 0.0

        for asset in account["balances"]:
            free = float(asset["free"])
            locked = float(asset["locked"])
            total = free + locked

            if total > 0:
                if asset["asset"] == "USDT":
                    total_usdt += total
                else:
                    symbol = asset["asset"] + "USDT"
                    try:
                        price = float(main.BINANCE_CLIENT.get_symbol_ticker(symbol=symbol)["price"])
                        total_usdt += total * price
                    except:
                        pass

        if INITIAL_EQUITY is None:
            INITIAL_EQUITY = total_usdt

        btc_price = float(main.BINANCE_CLIENT.get_symbol_ticker(symbol="BTCUSDT")["price"])

        MAX_POINTS = 500

        EQUITY_HISTORY.append(total_usdt)
        BTC_HISTORY.append(btc_price)

        if len(EQUITY_HISTORY) > MAX_POINTS:
            EQUITY_HISTORY.pop(0)
            BTC_HISTORY.pop(0)

        equity_array = np.array(EQUITY_HISTORY)

        returns = np.diff(equity_array) / equity_array[:-1] if len(equity_array) > 1 else np.array([0])

        cumulative_pct = ((total_usdt / INITIAL_EQUITY) - 1) * 100

        peak = np.maximum.accumulate(equity_array)
        drawdown = (equity_array - peak) / peak
        max_drawdown = drawdown.min() * 100 if len(drawdown) > 0 else 0

        if len(returns) > 1 and np.std(returns) != 0:
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252)
        else:
            sharpe = 0

        return {
            "equity": round(total_usdt, 2),
            "cumulative_pct": round(cumulative_pct, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe": round(sharpe, 2),
            "btc_price": btc_price
        }

    except Exception as e:
        print("Erro equity:", e)
        return {
            "equity": 0,
            "cumulative_pct": 0,
            "max_drawdown": 0,
            "sharpe": 0,
            "btc_price": 0
        }
    
# ---------------------------------------

if __name__ == "__main__":
    print("🌐 Dashboard Profissional iniciado...")
    app.run(host="0.0.0.0", port=5000)