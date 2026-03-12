import time

BUY = "BUY"
SELL = "SELL"
HOLD = None


class StrategyRunner:

    LAST_DECISION = None
    LAST_DECISION_TIME = 0

    CACHE_SECONDS = 10

    @staticmethod
    def execute(
        bot,
        main_strategy,
        fallback_strategy,
        stock_data,
        main_strategy_args=None,
        fallback_strategy_args=None,
        verbose=True
    ):

        try:

            # ------------------------------
            # CACHE (item 3)

            if time.time() - StrategyRunner.LAST_DECISION_TIME < StrategyRunner.CACHE_SECONDS:

                if verbose:
                    print("⚡ Usando decisão em cache")

                return StrategyRunner.LAST_DECISION

            # ------------------------------
            # executar estratégia principal

            main_strategy_args = main_strategy_args or {}

            main_strategy_args.update({
                "bot": bot,
                "stock_data": stock_data,
                "verbose": verbose
            })

            try:

                result = main_strategy(**main_strategy_args)

            except Exception as e:

                print("❌ Erro na estratégia principal:", e)
                result = HOLD

            # ------------------------------
            # fallback

            if result is HOLD and fallback_strategy and bot.fallback_activated:

                if verbose:
                    print("⚠️ Estratégia principal inconclusiva")
                    print("🔁 Executando fallback")

                fallback_strategy_args = fallback_strategy_args or {}

                fallback_strategy_args.update({
                    "bot": bot,
                    "stock_data": stock_data,
                    "verbose": verbose
                })

                try:

                    result = fallback_strategy(**fallback_strategy_args)

                except Exception as e:

                    print("❌ Erro na fallback:", e)
                    result = HOLD

            # ------------------------------
            # salvar cache

            StrategyRunner.LAST_DECISION = result
            StrategyRunner.LAST_DECISION_TIME = time.time()

            # ------------------------------
            # log (item 6)

            if verbose:

                print(
                    f"🧠 Strategy decision | "
                    f"{bot.operation_code} | "
                    f"{result}"
                )

            return result

        except Exception as e:

            print("❌ Erro no StrategyRunner:", e)
            return HOLD