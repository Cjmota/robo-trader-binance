import time
from src.state import STATE

def log_trade(symbol, profit):

    STATE["trades"].append({
        "symbol": symbol,
        "profit": profit,
        "time": time.time()
    })

    # limita histórico
    if len(STATE["trades"]) > 500:
        STATE["trades"].pop(0)

    print(f"📊 Trade registrado: {symbol} | Profit: {profit:.2f}%")