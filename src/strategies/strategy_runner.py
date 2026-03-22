import time
from src.strategies.rsi_strategy import getRsiTradeStrategy

BUY = "BUY"
SELL = "SELL"
HOLD = None #"HOLD"

def extract_signal(result, HOLD=None):
        if result is None:
            return HOLD
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return result.get("signal") or result.get("action") or HOLD
        return HOLD

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
            

           # -------------------------------
            # 🔒 CACHE (LEITURA)
            if symbol in self.cache:
                cached = self.cache[symbol]

                if isinstance(cached, tuple) and len(cached) == 2:
                    decision, timestamp = cached

                    if now - timestamp < self.cache_seconds:
                        if verbose:
                            print(f"⚡ Cache {symbol}: {decision}")
                        return decision
                else:
                    # limpa cache corrompido
                    print(f"⚠️ Cache inválido para {symbol}, limpando...")
                    del self.cache[symbol]

            # -------------------------------
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

            # 🔒 blindagem
            if result is None:
                result = HOLD

            result_signal = extract_signal(result, HOLD)

            # -------------------------------
            # 🔁 FALLBACK
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

                if result is None:
                    result = HOLD

                result_signal = extract_signal(result, HOLD)

            # -------------------------------
            # 🧠 NORMALIZAÇÃO
            if isinstance(result, dict):
                decision = {**default_decision, **result}
            
            # 🔥 GARANTE VALORES MÍNIMOS
            if decision["signal"] != HOLD:
                if decision.get("score", 0) == 0:
                    decision["score"] = 0.4 if decision["signal"] == BUY else -0.4

                if decision.get("probability", 0) == 0:
                    decision["probability"] = 0.5

            elif isinstance(result, str):
                decision = {**default_decision, "signal": result}

            else:
                decision = default_decision.copy()
                
            if not decision.get("signal"):
                decision["signal"] = HOLD

            # 🔒 garantia final
            if "signal" not in decision:
                decision["signal"] = HOLD

            # -------------------------------
            # 💾 CACHE
            # só cacheia se for útil
            if decision["signal"] != HOLD:
                self.cache[symbol] = (decision, now)

            # -------------------------------
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


def rsi_strategy_wrapper(bot, stock_data, verbose=True, **kwargs):

    signal = getRsiTradeStrategy(
        bot=bot,
        stock_data=stock_data,
        verbose=verbose
    )

    if signal is None:
        signal = HOLD

    # -------------------------
    # 📊 RSI seguro

    try:
        df = stock_data.rename(columns={"close_price": "close"}).copy()

        from src.indicators.indicators import Indicators
        df["RSI"] = Indicators.getRSI(df, last_only=False)

        rsi_clean = df["RSI"].dropna()

        if rsi_clean.empty:
            return {
                "signal": HOLD,
                "score": 0,
                "probability": 0
            }

        last_rsi = rsi_clean.iloc[-1]

    except Exception as e:
        print("❌ Erro RSI:", e)
        return {
            "signal": HOLD,
            "score": 0,
            "probability": 0
        }

    # -------------------------
    # 🔥 PROB DINÂMICA

    distance = abs(last_rsi - 50)

    if distance > 25:
        probability = 0.7
    elif distance > 15:
        probability = 0.6
    else:
        probability = 0.5

    # -------------------------
    # 🔥 SCORE CORRETO

    if signal == BUY:
        score = 0.4
    elif signal == SELL:
        score = -0.4
    else:
        score = 0

    return {
        "signal": signal,
        "score": score,
        "probability": probability,
        "regime": "SIDEWAYS",
        "momentum": distance > 10,
        "volume_spike": distance > 15,
        "orderflow": "NEUTRAL"
    }