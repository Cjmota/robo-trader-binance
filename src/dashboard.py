from flask import Flask, render_template, request, jsonify
from datetime import datetime
import threading
import json
import os
import logging
import numpy as np

from src import main
from src.utils.performance import calculate_metrics

# ----------------------------------------
# CONFIG
# ----------------------------------------

logging.basicConfig(filename="dashboard.log", level=logging.INFO)

app = Flask(__name__, template_folder="templates", static_folder="static")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app", "config.json")

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
    return main.CURRENT_TRADER

# ----------------------------------------
# ROUTES
# ----------------------------------------

@app.route("/")
def home():
    return render_template("dashboard.html", metrics=calculate_metrics())


@app.route("/status")
def status():
    t = get_trader()

    return jsonify({
        "running": main.BOT_RUNNING,
        "asset": t.operation_code if t else "Nenhum",
        "position": "Comprado" if t and t.actual_trade_position else "Sem posição",
        "daily_profit": round(getattr(t, "daily_profit", 0), 4) if t else 0
    })


@app.route("/botinfo")
def botinfo():
    t = get_trader()

    if not t:
        return jsonify({"active": False})

    pnl_usdt, pnl_pct = t.getCurrentOperationProfit()

    return jsonify({
        "active": True,
        "asset": t.operation_code,
        "pnl_usdt": pnl_usdt,
        "pnl_pct": pnl_pct,
        "strategy": t.main_strategy.__name__
    })


@app.route("/start", methods=["POST"])
def start():

    if main.BOT_RUNNING:
        return jsonify({"status": "already_running"})

    print("🔥 START CHAMADO")

    main.BOT_RUNNING = True

    # 🚀 roda direto (sem thread)
    try:
        main.safe_trader_master_loop()
    except Exception as e:
        print("❌ ERRO:", e)

    return jsonify({"status": "started"})


@app.route("/stop", methods=["POST"])
def stop():
    if not main.BOT_RUNNING:
        return jsonify({"status": "already_stopped"})

    main.BOT_RUNNING = False

    return jsonify({"status": "stopped"})

@app.route("/trades")
def trades():
    return jsonify(main.TRADE_HISTORY[-200:])


# ----------------------------------------
# EQUITY (simplificado)
# ----------------------------------------

@app.route("/equity")
def equity():
    global INITIAL_EQUITY

    try:
        client = main.BINANCE_CLIENT
        if not client:
            return jsonify({"equity": 0})

        account = client.get_account()

        total = 0
        for a in account["balances"]:
            qty = float(a["free"]) + float(a["locked"])
            if qty <= 0:
                continue

            if a["asset"] == "USDT":
                total += qty
            else:
                try:
                    price = float(client.get_symbol_ticker(symbol=a["asset"]+"USDT")["price"])
                    total += qty * price
                except:
                    pass

        if INITIAL_EQUITY is None:
            INITIAL_EQUITY = total

        EQUITY_HISTORY.append(total)
        if len(EQUITY_HISTORY) > 300:
            EQUITY_HISTORY.pop(0)

        arr = np.array(EQUITY_HISTORY)

        returns = np.diff(arr) / arr[:-1] if len(arr) > 1 else np.array([0])
        sharpe = (np.mean(returns)/np.std(returns))*np.sqrt(252) if np.std(returns) else 0

        return jsonify({
            "equity": round(total,2),
            "pnl_pct": round(((total/INITIAL_EQUITY)-1)*100,2),
            "sharpe": round(sharpe,2)
        })

    except Exception as e:
        logging.error("equity error", exc_info=True)
        return jsonify({"equity": 0})


# ----------------------------------------
# SCANNER
# ----------------------------------------

@app.route("/scanner")
def scanner():
    return jsonify([
        {
            "symbol": s[0],
            "score": round(s[1],2),
            "momentum": round(s[2],4)
        }
        for s in main.SCANNER_RANKING
    ])


# ----------------------------------------
# CONFIG
# ----------------------------------------

@app.route("/config", methods=["GET"])
def get_cfg():
    return load_config()


@app.route("/config", methods=["POST"])
def set_cfg():
    cfg = load_config()
    data = request.json

    cfg["RISK"]["MAX_TRADES_PER_DAY"] = int(data["MAX_TRADES_PER_DAY"])
    cfg["STOP_LOSS_PERCENTAGE"] = float(data["STOP_LOSS_PERCENTAGE"])

    save_config(cfg)
    return {"status": "ok"}


# ----------------------------------------
# HEALTH
# ----------------------------------------

@app.route("/health")
def health():
    return {
        "status": "ok",
        "running": main.BOT_RUNNING,
        "time": datetime.now().isoformat()
    }