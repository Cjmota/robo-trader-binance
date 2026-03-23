from flask import Flask, render_template, request, jsonify
from src.main import safe_trader_master_loop
from datetime import datetime
from src.state import STATE

import threading
import json
import os
import logging
import numpy as np

import src.main as main
from src.utils.performance import calculate_metrics

# ----------------------------------------
# CONFIG
# ----------------------------------------

logging.basicConfig(filename="dashboard.log", level=logging.INFO)

app = Flask(__name__, template_folder="templates", static_folder="static")


bot_loop_started = False

def start_background_loop():
    global bot_loop_started

    if bot_loop_started:
        print("⚠️ Loop já iniciado")
        return

    thread = threading.Thread(
        target=safe_trader_master_loop,
        daemon=True
    )
    thread.start()

    bot_loop_started = True
    print("🧠 Loop do bot iniciado em background")

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found"}), 404

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

EQUITY_HISTORY = []
BTC_HISTORY = []
INITIAL_EQUITY = None

bot_thread = None

# ----------------------------------------
# HELPERS
# ----------------------------------------

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print("⚠️ config.json não encontrado, criando padrão...")

        default_config = {
            "RISK": {
                "MAX_TRADES_PER_DAY": 10,
                "SYMBOL_COOLDOWN": 60,
                "LOSS_COOLDOWN": 120,
                "MAX_POSITION_PERCENT": 0.05
            },
            "STOP_LOSS_PERCENTAGE": 1.0,
            "TP_AT_PERCENTAGE": [1.0, 2.0],
            "TEMPO_ENTRE_TRADES": 10
        }

        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)

        with open(CONFIG_PATH, "w") as f:
            json.dump(default_config, f, indent=4)

        return default_config

    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)

def get_trader():
    return getattr(main, "CURRENT_TRADER", None)

def ok(data=None):
    return jsonify({
        "success": True,
        "data": clean(data)
    })

def fail(msg="error"):
    return jsonify({
        "success": False,
        "error": msg
    })

def clean(obj):
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean(x) for x in obj]
    elif isinstance(obj, (np.integer, np.floating)):
        return float(obj)
    elif isinstance(obj, (np.bool_)):
        return bool(obj)
    return obj

# ----------------------------------------
# ROUTES
# ----------------------------------------

@app.route("/")
def home():
    return render_template("dashboard.html", metrics=calculate_metrics())

@app.route("/api/status")
def status():

    bot = getattr(main, "CURRENT_TRADER", None)

    return ok({
        "running": main.BOT_RUNNING,
        "asset": getattr(bot, "symbol", "-"),
        "position": "OPEN" if bot and getattr(bot, "position_open", False) else "NONE",
        "daily_profit": getattr(bot, "daily_profit", 0)
    })

@app.route("/api/botinfo")
def api_botinfo():
    try:
        t = getattr(main, "CURRENT_TRADER", None)

        if not t:
            return ok({"active": False})

        if not t.position_open:
            return ok({
                "active": False,
                "position_open": False
            })

        price = float(t.get_price())
        entry = float(t.entry_price)
        qty = float(t.quantity)

        pnl_usdt = float((price - entry) * qty)
        pnl_pct = float((price - entry) / entry * 100)

        return ok({
            "active": True,
            "position_open": True,
            "symbol": t.symbol,
            "entry_price": entry,
            "current_price": price,
            "quantity": qty,
            "pnl_usdt": pnl_usdt,
            "pnl_pct": pnl_pct,
            "strategy": getattr(t.main_strategy, "__name__", "N/A")
        })

    except Exception as e:
        return fail(str(e))

@app.route("/start", methods=["POST"])
def start():
    threading.Thread(target=main.start_bot, daemon=True).start()
    return ok({"status": "started"})

@app.route("/stop", methods=["POST"])
def stop():
    main.stop_bot()
    return jsonify({"status": "stopped"})

@app.route("/api/trades")
def api_trades():
    return ok({
        "trades": STATE["trades"]
    })

# ----------------------------------------
# EQUITY (simplificado)
# ----------------------------------------

import random

@app.route("/api/equity")
def api_equity():

    return ok({
        "equity": STATE["equity"],
        "btc_price": STATE["btc_price"],
        "cumulative_pct": 0,
        "max_drawdown": 0,
        "sharpe": 0
    })

# ----------------------------------------
# SCANNER
# ----------------------------------------

@app.route("/api/scanner")
def api_scanner():
    try:
        data = getattr(main, "SCANNER_RANKING", [])

        return ok({
            "ranking": [
                {
                    "symbol": s[0],
                    "score": float(s[1]),
                    "momentum": float(s[2]),
                    "volume": 1000000
                }
                for s in data
            ],
            "smart_money": ["BUY BTC", "SELL ETH"]
        })
    except Exception as e:
        return fail(str(e))

# ----------------------------------------
# CONFIG
# ----------------------------------------

@app.route("/api/config", methods=["GET"])
def api_get_config():
    return ok(load_config())


@app.route("/api/config", methods=["POST"])
def api_set_config():
    cfg = load_config()
    data = request.json

    cfg["STOP_LOSS_PERCENTAGE"] = data["STOP_LOSS_PERCENTAGE"]
    cfg["TP_AT_PERCENTAGE"] = data["TP_AT_PERCENTAGE"]
    cfg["TEMPO_ENTRE_TRADES"] = data["TEMPO_ENTRE_TRADES"]

    cfg["RISK"]["MAX_POSITION_PERCENT"] = data["MAX_POSITION_PERCENT"] / 100
    cfg["RISK"]["MAX_TRADES_PER_DAY"] = data["MAX_TRADES_PER_DAY"]
    cfg["RISK"]["SYMBOL_COOLDOWN"] = data["SYMBOL_COOLDOWN"]
    cfg["RISK"]["LOSS_COOLDOWN"] = data["LOSS_COOLDOWN"]

    save_config(cfg)

    return ok({"saved": True})
# ----------------------------------------
# HEALTH
# ----------------------------------------

@app.route("/health")
def health():
    return ok({
        "status": "ok",
        "running": main.BOT_RUNNING,
        "time": datetime.now().isoformat()
    })

@app.route("/api/heatmap")
def api_heatmap():
    return ok([
        {"symbol": "BTC", "change": 2.1},
        {"symbol": "ETH", "change": -1.3}
    ])
        
@app.route("/api/performance")
def api_performance():
    return ok({
        "total_trades": 10,
        "win_rate": 0.6,
        "profit_factor": 1.8,
        "expectancy": 0.02,
        "sharpe": 1.5
    })

start_background_loop()  # 🔥 inicia o bot

if __name__ == "__main__":

    

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False  # 🔥 AQUI
    )