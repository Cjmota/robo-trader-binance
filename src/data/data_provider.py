import time
import pandas as pd
from src.core.rate_limiter import rate_limiter
from src.utils.safe_api import safe_api_call

data_cache = {}
data_time = {}

def get_klines(client, symbol, interval="5m"):

    now = time.time()

    # 🔥 CACHE 30s
    if symbol in data_cache and now - data_time[symbol] < 30:
        return data_cache[symbol]

    rate_limiter.wait()

    candles = safe_api_call(
        client.get_klines,
        symbol=symbol,
        interval=interval,
        limit=50
    )

    if not candles:
        return None

    df = pd.DataFrame(candles)

    df["close_price"] = pd.to_numeric(df[4])
    df["high_price"] = pd.to_numeric(df[2])
    df["low_price"] = pd.to_numeric(df[3])
    df["volume"] = pd.to_numeric(df[5])

    data_cache[symbol] = df
    data_time[symbol] = now

    return df