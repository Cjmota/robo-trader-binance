import pandas as pd


def get_capital_flow_score(client, symbol):

    try:

        candles = client.get_klines(
            symbol=symbol,
            interval="5m",
            limit=30
        )

        df = pd.DataFrame(candles)

        df["close"] = pd.to_numeric(df[4])
        df["volume"] = pd.to_numeric(df[5])

        df["quote_volume"] = df["close"] * df["volume"]

        price_change = (
            df["close"].iloc[-1] - df["close"].iloc[-5]
        ) / df["close"].iloc[-5]

        avg_vol = df["quote_volume"].iloc[-20:-5].mean()
        recent_vol = df["quote_volume"].iloc[-5:].mean()

        if avg_vol == 0:
            return 0

        volume_growth = recent_vol / avg_vol

        score = price_change * 5 + volume_growth

        return score

    except Exception:

        return 0


def scan_capital_flow(client, symbols):

    results = []

    for symbol in symbols:

        score = get_capital_flow_score(client, symbol)

        results.append({
            "symbol": symbol,
            "score": score
        })

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results[:5]