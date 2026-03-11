import pandas as pd


def scan_market_pro(client):

    print("🔎 Escaneando mercado inteligente PRO...")

    try:
        tickers = client.get_ticker()
    except Exception as e:
        print("Erro ao obter tickers:", e)
        return []

    candidates = []

    # -------------------------------------------------
    # FILTRO 1 — LIQUIDEZ E MOVIMENTO
    # -------------------------------------------------

    for ticker in tickers:

        symbol = ticker["symbol"]

        if not symbol.endswith("USDT"):
            continue

        # evitar stablecoins
        if symbol.startswith(("USDC", "BUSD", "TUSD", "FDUSD")):
            continue

        try:

            quote_volume = float(ticker.get("quoteVolume", 0))
            price_change = abs(float(ticker.get("priceChangePercent", 0)))

        except:
            continue

        # filtro liquidez mínima
        if quote_volume < 2_000_000:
            continue

        # filtro volatilidade mínima
        if price_change < 0.5:
            continue

        candidates.append(symbol)

    print(f"📊 Ativos candidatos após filtro: {len(candidates)}")

    results = []

    # -------------------------------------------------
    # FILTRO 2 — ANÁLISE DE CANDLE
    # -------------------------------------------------

    for symbol in candidates[:80]:  # limite segurança API

        try:

            candles = client.get_klines(
                symbol=symbol,
                interval="5m",
                limit=50
            )

            if not candles:
                continue

            df = pd.DataFrame(candles)

            df["close"] = pd.to_numeric(df[4])
            df["volume"] = pd.to_numeric(df[5])

            closes = df["close"]
            volumes = df["volume"]

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            if avg_volume == 0:
                continue

            volume_growth = current_volume > avg_volume * 1.5

            price_change = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]

            recent_range = (
                closes.iloc[-20:].max() - closes.iloc[-20:].min()
            ) / closes.iloc[-20:].min()

            volatility = closes.pct_change().std()

            score = 0

            # -------------------------------------------------
            # SCORE
            # -------------------------------------------------

            if volume_growth:
                score += 3

            if price_change > 0:
                score += 2

            if recent_range < 0.03:
                score += 2

            if current_volume > avg_volume * 2:
                score += 3

            if volatility > 0.002:
                score += 2

            if score >= 6:

                results.append({
                    "symbol": symbol,
                    "score": score,
                    "volume": current_volume
                })

        except Exception:
            continue

    # -------------------------------------------------
    # RANKING
    # -------------------------------------------------

    results = sorted(results, key=lambda x: x["score"], reverse=True)

    top_symbols = [r["symbol"] for r in results[:10]]

    print(f"🔥 TOP OPORTUNIDADES: {top_symbols}")

    return top_symbols