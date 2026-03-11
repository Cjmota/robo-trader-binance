class StrategyRunner:

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

            main_strategy_args = main_strategy_args or {}
            main_strategy_args.update({
                "bot": bot,
                "stock_data": stock_data,
                "verbose": verbose
            })

            result = main_strategy(**main_strategy_args)

            if result is None:

                if fallback_strategy and bot.fallback_activated:

                    if verbose:
                        print("⚠️ Estratégia principal inconclusiva")
                        print("🔁 Executando fallback...")

                    fallback_strategy_args = fallback_strategy_args or {}
                    fallback_strategy_args.update({
                        "bot": bot,
                        "stock_data": stock_data,
                        "verbose": verbose
                    })

                    result = fallback_strategy(**fallback_strategy_args)

            return result

        except Exception as e:

            print("❌ Erro no StrategyRunner:", e)
            return None