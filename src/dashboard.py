from flask import Flask, render_template, request, jsonify
from src.main import SCANNER_RANKING, SCANNER_SMART_MONEY
from flask import Response
from datetime import datetime
import numpy as np
import threading
from src import main
import json
import os
import logging

logging.basicConfig(
filename="dashboard.log",
level=logging.INFO
)

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

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)

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
        "daily_profit": round(getattr(trader, "daily_profit", 0), 4) if trader else 0,
        "sleep_time": trader.time_to_sleep if trader else 0
    })

@app.route("/botinfo")
def botinfo():

    trader = main.CURRENT_TRADER

    if not trader:
        return jsonify({
            "active": False,
            "running": main.BOT_RUNNING
        })

    pnl_usdt, pnl_pct = trader.getCurrentOperationProfit()

    return jsonify({
        "active": True,
        "running": main.BOT_RUNNING,
        "asset": trader.operation_code,
        "pnl_usdt": pnl_usdt,
        "pnl_pct": pnl_pct,
        "strategy": trader.main_strategy.__name__,
        "cooldowns": len(main.symbol_cooldown),
        "memory_assets": len(main.MARKET_MEMORY)
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
        return jsonify({"status":"started"})
    return jsonify({"status":"already_running"})

# ---------------- STOP ----------------
@app.route("/stop", methods=["POST"])
def stop_bot():
    main.BOT_RUNNING = False
    return jsonify({"status":"stopped"})

# ---------------- CONFIG ----------------

@app.route("/trades")
def get_trades():
    return jsonify(main.TRADE_HISTORY)

@app.route("/equity")
def equity():
    global INITIAL_EQUITY

    try:
        if not hasattr(main, "BINANCE_CLIENT") or main.BINANCE_CLIENT is None:
            return jsonify({
                "equity": 0,
                "cumulative_pct": 0,
                "max_drawdown": 0,
                "sharpe": 0,
                "btc_price": 0
            })

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
                        ticker = main.BINANCE_CLIENT.get_symbol_ticker(symbol=symbol)

                        if ticker:
                            price = float(ticker["price"])
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

        return jsonify({
            "equity": round(total_usdt, 2),
            "cumulative_pct": round(cumulative_pct, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe": round(sharpe, 2),
            "btc_price": btc_price
        })

    except Exception as e:
        print("Erro equity:", e)
        return jsonify({
            "equity": 0,
            "cumulative_pct": 0,
            "max_drawdown": 0,
            "sharpe": 0,
            "btc_price": 0
        })
    
# ---------------------------------------

@app.route("/api/scanner")
def scanner():

    try:

        ranking = [
            {
                "symbol": s[0],
                "score": round(s[1], 2),
                "momentum": round(s[2], 4) if len(s) > 2 else 0,
                "volume": int(s[3]) if len(s) > 3 else 0
            }
            for s in SCANNER_RANKING
        ]

        return jsonify({
            "ranking": ranking,
            "smart_money": SCANNER_SMART_MONEY
        })

    except Exception as e:

        logging.error("Erro endpoint scanner", exc_info=True)

        return jsonify({
            "ranking": [],
            "smart_money": []
        })
    
@app.route("/api/config", methods=["GET"])
def get_config():
    return load_config()    
    
@app.route("/api/config", methods=["POST"])
def update_config():

    data = request.json
    config = load_config()

    config["RISK"]["MAX_TRADES_PER_DAY"] = int(data["MAX_TRADES_PER_DAY"])
    config["RISK"]["SYMBOL_COOLDOWN"] = int(data["SYMBOL_COOLDOWN"])
    config["RISK"]["LOSS_COOLDOWN"] = int(data["LOSS_COOLDOWN"])
    config["RISK"]["MAX_POSITION_PERCENT"] = float(data["MAX_POSITION_PERCENT"]) / 100
    config["STOP_LOSS_PERCENTAGE"] = float(data["STOP_LOSS_PERCENTAGE"])
    config["TP_AT_PERCENTAGE"] = data["TP_AT_PERCENTAGE"]
    config["TEMPO_ENTRE_TRADES"] = int(data["TEMPO_ENTRE_TRADES"])
    

    save_config(config)

    return {"status": "ok"}

@app.route("/health")
def health():
    return {
        "status": "ok",
        "bot_running": main.BOT_RUNNING,
        "time": datetime.now().isoformat()
    }

@app.route("/api/heatmap")
def heatmap():

    ranking = main.SCANNER_RANKING

    data = []

    for r in ranking:

        data.append({
            "symbol": r[0],
            "change": round(r[2] * 100, 2)
        })

    return jsonify(data)