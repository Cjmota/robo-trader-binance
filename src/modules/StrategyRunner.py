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

        main_strategy_args = main_strategy_args or {}
        main_strategy_args["stock_data"] = stock_data
        main_strategy_args["bot"] = bot
        main_strategy_args["verbose"] = verbose

        final_decision = main_strategy(**main_strategy_args)

        if final_decision is None and bot.fallback_activated:

            print("Estratégia principal inconclusiva")
            print("Executando estratégia de fallback...")

            fallback_strategy_args = fallback_strategy_args or {}
            fallback_strategy_args["stock_data"] = stock_data
            fallback_strategy_args["bot"] = bot
            fallback_strategy_args["verbose"] = verbose

            final_decision = fallback_strategy(**fallback_strategy_args)

        return final_decision