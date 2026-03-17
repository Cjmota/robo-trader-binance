import pandas as pd


def scan_market_pro(client):

    print("🔎 Scanner PRO otimizado...")

    try:
        tickers = client.get_ticker()
    except Exception as e:
        print("Erro ao obter tickers:", e)
        return []

    # -----------------------------------------
    # 1️⃣ FILTRO RÁPIDO (sem API extra)
    # -----------------------------------------
    candidates = [
        t["symbol"]
        for t in tickers
        if (
            t["symbol"].endswith("USDT")
            and not t["symbol"].startswith(("USDC", "BUSD", "TUSD", "FDUSD"))
            and float(t.get("quoteVolume", 0)) > 2_000_000
            and abs(float(t.get("priceChangePercent", 0))) > 0.5
        )
    ]

    print(f"📊 Candidatos: {len(candidates)}")

    results = []

    # -----------------------------------------
    # 2️⃣ ANÁLISE (limitada + eficiente)
    # -----------------------------------------
    for symbol in candidates[:50]:  # 🔥 reduzi 80 → 50

        try:
            candles = client.get_klines(symbol=symbol, interval="5m", limit=50)
            if not candles:
                continue

            df = pd.DataFrame(candles)

            closes = pd.to_numeric(df[4])
            volumes = pd.to_numeric(df[5])

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            if avg_volume == 0:
                continue

            price_change = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]
            volatility = closes.pct_change().std()

            # -----------------------------------------
            # SCORE INTELIGENTE (normalizado)
            # -----------------------------------------
            score = 0

            # volume
            vol_ratio = current_volume / avg_volume
            score += min(vol_ratio, 3)

            # momentum
            if price_change > 0:
                score += 2

            # compressão (pré breakout)
            recent_range = (
                closes.iloc[-20:].max() - closes.iloc[-20:].min()
            ) / closes.iloc[-20:].min()

            if recent_range < 0.03:
                score += 2

            # volatilidade saudável
            if volatility > 0.002:
                score += 1.5

            # filtro final
            if score >= 4.5:
                results.append((symbol, score))

        except Exception:
            continue

    # -----------------------------------------
    # 3️⃣ RANKING
    # -----------------------------------------
    results.sort(key=lambda x: x[1], reverse=True)

    top_symbols = [r[0] for r in results[:10]]

    print(f"🔥 TOP: {top_symbols}")

    return top_symbols