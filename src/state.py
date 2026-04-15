import threading
lock = threading.Lock()

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
    "running": True
}

stocks_traded_list = []