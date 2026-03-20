import time

def safe_api_call(func, *args, **kwargs):

    for i in range(5):
        try:
            return func(*args, **kwargs)

        except Exception as e:

            if "1003" in str(e):
                wait = (i + 1) * 15
                print(f"🚫 BAN detectado... aguardando {wait}s")
                time.sleep(wait)
            else:
                print("❌ Erro API:", e)
                return None

    return None