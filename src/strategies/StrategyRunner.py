import time
from src.strategies.rsi_strategy import getRsiTradeStrategy

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
            
            symbol = getattr(bot, "operation_code", None)
            
            default_decision = {
                "signal": HOLD,
                "score": 0,
                "probability": 0,
                "regime": "UNKNOWN",
                "spread": 0,
                "volume_spike": False,
                "momentum": False,
                "orderflow": "NEUTRAL"
            }

            if not symbol:
                return default_decision.copy()
                
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

            result_signal = result if isinstance(result, str) else result.get("signal", HOLD)

            if result_signal == HOLD and fallback_strategy and bot.fallback_activated:

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
                
                # 🔥 recalcula depois do fallback
                result_signal = result if isinstance(result, str) else result.get("signal", HOLD)

            # -----------------------------------
            # 🧠 NORMALIZAÇÃO PROFISSIONAL

            

            if isinstance(result, dict):
                decision = {**default_decision, **result}

            elif result in [BUY, SELL, HOLD]:
                decision = {**default_decision, "signal": result}

            else:
                decision = default_decision.copy()

            # -----------------------------------
            # 💾 CACHE
            
            if "signal" not in decision:
                decision["signal"] = HOLD

            self.cache[symbol] = (decision, now)

            # -----------------------------------
            # LOG

            if verbose:
               print(f"🧠 {symbol} → {decision['signal']} | score={decision['score']} | prob={decision['probability']}")

            return decision

        except Exception as e:
            print("❌ StrategyRunner erro geral:", e)

            return {
                "signal": HOLD,
                "score": 0,
                "probability": 0,
                "regime": "UNKNOWN",
                "spread": 0,
                "volume_spike": False,
                "momentum": False,
                "orderflow": "NEUTRAL"
            }
    
    from src.strategies.rsi_strategy import getRsiTradeStrategy

def rsi_strategy_wrapper(bot, stock_data):

    signal = getRsiTradeStrategy(
        bot=bot,
        stock_data=stock_data,
        verbose=True
    )

    if signal is None:
        return {
            "signal": "HOLD",
            "score": 0,
            "probability": 0
        }

    # -------------------------
    # 📊 calcular RSI atual

    last_rsi = stock_data["close_price"].copy()

    from src.indicators import Indicators
    rsi_series = Indicators.getRSI(last_rsi, last_only=False)

    last_rsi = rsi_series.iloc[-1]

    # -------------------------
    # 🔥 PROB DINÂMICA

    probability = 0.65 if abs(last_rsi - 50) > 20 else 0.55

    # -------------------------
    # 🔥 SCORE

    score = 0.4 if signal == "BUY" else -0.4

    return {
        "signal": signal,
        "score": score,
        "probability": probability,
        "regime": "SIDEWAYS",
        "momentum": True,
        "volume_spike": True,
        "orderflow": "NEUTRAL"
    }