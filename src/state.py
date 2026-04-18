import threading
lock = threading.Lock()

best_asset = {
    "symbol": None,
    "score": 0
}

bot_status = {
    "status": "running",
    "last_update": None,
    "balance": 0,
    "positions": {},
    "price_history": [],
    "candles": [],
    "pnl": 0,
    "pnl_percent": 0
}

bot_control = {
    "running": True,
    "buying_now": False,
    "selling_now": False
}

stocks_traded_list = []