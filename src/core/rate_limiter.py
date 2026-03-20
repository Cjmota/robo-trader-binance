import time

class RateLimiter:

    def __init__(self, max_calls=100, period=60):
        self.max_calls = max_calls
        self.period = period
        self.calls = []

    def wait(self):
        now = time.time()

        self.calls = [c for c in self.calls if now - c < self.period]

        if len(self.calls) >= self.max_calls:
            sleep_time = self.period - (now - self.calls[0])
            print(f"⏳ Rate limit... aguardando {sleep_time:.2f}s")
            time.sleep(max(sleep_time, 1))

        self.calls.append(time.time())


# 🔥 instância global
rate_limiter = RateLimiter(100, 60)