import time

def safe_api_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)

    except Exception as e:
        msg = str(e)

        # 🚫 ERRO DE SÍMBOLO INVÁLIDO (BINANCE)
        if "-1121" in msg:
            print(f"🚫 Símbolo inválido ignorado")
            return None

        # 🔁 RATE LIMIT / TEMPORÁRIO
        if "1003" in msg or "Too many requests" in msg:
            print("⏳ Rate limit - aguardando...")
            time.sleep(1)
            return None

        # 🔥 OUTROS ERROS
        print(f"❌ Erro API: {e}")
        return None