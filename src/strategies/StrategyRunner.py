import time

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class StrategyRunner:

    def __init__(self):
        self.cache = {}  # 🔥 cache por símbolo

        self.cache_seconds = 10

    def execute(
        self,
        bot,
        main_strategy,
        fallback_strategy,
        stock_data,
        main_strategy_args=None,
        fallback_strategy_args=None,
        verbose=True
    ):

        try:

            symbol = bot.operation_code
            now = time.time()

            # -----------------------------------
            # 🔒 CACHE POR ATIVO
            if symbol in self.cache:

                decision, timestamp = self.cache[symbol]

                if now - timestamp < self.cache_seconds:

                    if verbose:
                        print(f"⚡ Cache {symbol}: {decision}")

                    return decision

            # -----------------------------------
            # 🧠 MAIN STRATEGY

            args_main = {
                "bot": bot,
                "stock_data": stock_data,
                "verbose": verbose,
                **(main_strategy_args or {})
            }

            try:
                result = main_strategy(**args_main)
            except Exception as e:
                print(f"❌ Erro main ({symbol}):", e)
                result = HOLD

            # -----------------------------------
            # 🔁 FALLBACK

            if result == HOLD and fallback_strategy and bot.fallback_activated:

                if verbose:
                    print("🔁 Fallback acionado")

                args_fallback = {
                    "bot": bot,
                    "stock_data": stock_data,
                    "verbose": verbose,
                    **(fallback_strategy_args or {})
                }

                try:
                    result = fallback_strategy(**args_fallback)
                except Exception as e:
                    print(f"❌ Erro fallback ({symbol}):", e)
                    result = HOLD

            # -----------------------------------
            # 🧠 NORMALIZAÇÃO

            if result not in [BUY, SELL, HOLD]:
                result = HOLD

            # -----------------------------------
            # 💾 CACHE

            self.cache[symbol] = (result, now)

            # -----------------------------------
            # LOG

            if verbose:
                print(f"🧠 {symbol} → {result}")

            return result

        except Exception as e:
            print("❌ StrategyRunner erro geral:", e)
            return HOLD