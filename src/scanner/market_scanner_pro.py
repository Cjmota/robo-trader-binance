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

    ranking = []
    smart_money = []

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
            score += min(vol_ratio, 1.5)

            # momentum
            if abs(price_change) > 0:
                score += 1.5

            # compressão (pré breakout)
            recent_range = (
                closes.iloc[-20:].max() - closes.iloc[-20:].min()
            ) / closes.iloc[-20:].min()

            if recent_range < 0.03:
                score += 1.5

            # volatilidade saudável
            if volatility > 0.002:
                score += 1
                
            # 🔥 DETECÇÃO DE SINAL (Smart Money)
            signal = None

            if price_change > 0.002 and vol_ratio > 1.8:
                signal = "BUY"
            elif price_change < -0.002 and vol_ratio > 1.8:
                signal = "SELL"

            # 🔥 SEMPRE ENTRA NO RANKING
            if score >= 2:
                ranking.append({
                    "symbol": symbol,
                    "score": round(score * 10),
                    "momentum": "UP" if price_change > 0 else "DOWN",
                    "volume": int(avg_volume)
                })

            # 🔥 SMART MONEY (se houver sinal)
            if signal:
                smart_money.append(f"{signal} {symbol}")

        except Exception as e:
            print(f"Erro em {symbol}: {e}")
            continue

    # -----------------------------------------
    # 3️⃣ RANKING
    # -----------------------------------------
    # ordenar ranking
    ranking = sorted(ranking, key=lambda x: x["score"], reverse=True)

    # limitar top 10
    ranking = ranking[:10]

    print(f"🔥 RANKING: {[r['symbol'] for r in ranking]}")
    print(f"💰 SMART MONEY: {smart_money}")

    # fallback (evita vazio)
    if not ranking and smart_money:
        for sm in smart_money:
            symbol = sm.split()[1]
            ranking.append({
                "symbol": symbol,
                "score": 50,
                "momentum": True,
                "volume": 0
            })

    # retorno padrão API
    return {
        "ranking": ranking,
        "smart_money": smart_money
    }