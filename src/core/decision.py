BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"

class DecisionEngine:

    def __init__(self, config):
        self.config = config
        self.min_prob = config.get("MIN_PROB", 0.45)

    def evaluate(self, signal_data):

        if not signal_data:
            return {"signal": HOLD, "score": 0, "probability": 0, "regime": "UNKNOWN"}

        signal = signal_data.get("signal")
        score = float(signal_data.get("score", 0))
        prob = float(signal_data.get("probability", 0))

        volume = signal_data.get("volume_spike", False)
        momentum = signal_data.get("momentum", False)
        regime = signal_data.get("regime", "UNKNOWN")

        # 🔥 CONSISTÊNCIA SCORE vs SIGNAL
        if score < 0 and signal == BUY:
            score = abs(score)

        if score > 0 and signal == SELL:
            score = -abs(score)

        # -----------------------------------------
        if signal is None:
            print("⚠️ Sem sinal → HOLD leve")
            return {"signal": HOLD, "score": 0.1, "probability": 0.3, "regime": regime}

        if score == 0:
            print("⚠️ Score zerado → ajustando")
            score = 0.4

        if prob < self.min_prob:
            print(f"⚠️ Prob baixa ({prob:.2f}) → reduzindo força")
            score *= 0.5

        if volume:
            score += 0.2

        if momentum:
            score += 0.2

        threshold = 0.25 if prob > 0.7 else 0.3

        if abs(score) >= threshold:
            return {
                "signal": signal,
                "score": round(score, 2),
                "probability": round(prob, 2),
                "regime": regime
            }

        print("🚫 Score final muito baixo")
        return {
            "signal": signal if prob > 0.6 else HOLD,
            "score": round(score, 2),
            "probability": prob,
            "regime": regime
        }
    
    # -----------------------------------------
    # 🔒 FILTROS

    def market_filter(self, bot, data):

        if bot is None:
            print("⚠️ Bot ausente")
            return False

        if not hasattr(bot, "marketRiskFilter"):
            print("⚠️ marketRiskFilter não existe")
            return True

        try:
            if not bot.marketRiskFilter(data):
                print("🌍 Mercado global ruim")
                return False
        except Exception as e:
            print(f"❌ Erro no marketRiskFilter: {e}")
            return False

        return True

    def regime_filter(self, signal, regime, momentum, orderflow):

        if regime == "SIDEWAYS":
            print("⚠️ Mercado lateral (permitido)")
            return True

        # 🔥 mais inteligente
        if regime == "TREND" and signal == SELL and orderflow == "BUY":
            print("⚠️ Contra tendência forte")
            return False

        return True

    def quality_filter(self, score, probability, signal):

        print(f"📊 Score: {score} | Prob: {probability:.2f}")
        
        if score > 0 and signal == SELL:
            print("⚠️ Score inconsistente com SELL (permitido)")
            
        if score < 0 and signal == BUY:
            print("⚠️ Score inconsistente com BUY (permitido)")

        # 🚫 score muito ruim
        if abs(score) < 0.1:
            print("⚠️ Score muito fraco")
            return False

        # 🚫 prob baixa
        if probability < 0.2:
            print("⛔ Probabilidade baixa")
            return False

        return True

    def flow_filter(self, signal, momentum, orderflow, volume_spike, score):

        strength = abs(score)

        strong_threshold = self.config.get("INTELLIGENCE", {}).get("FLOW_STRONG_THRESHOLD", 0.5)

        # -----------------------------------------
        # 🚫 sem momentum = nunca entra
        
        
        if not momentum:
            print("⚠️ Sem momentum (permitido)")

        # -----------------------------------------
        # 🧠 lógica adaptativa

        if strength < strong_threshold:

            if signal == BUY and orderflow != "BUY":
                print("⚠️ BUY sem fluxo (permitido em lateral)")
                # NÃO BLOQUEIA

            if signal == SELL and orderflow != "SELL":
                print("⚠️ SELL sem fluxo (permitido em lateral)")
                # NÃO BLOQUEIA

        else:

            if signal == BUY and orderflow == "SELL":
                print("⚠️ Fluxo contrário forte")
                return False

            if signal == SELL and orderflow == "BUY":
                print("⚠️ Fluxo contrário forte")
                return False

        # 🚫 BLOQUEIO REAL DE VOLUME
        if not volume_spike:
            print("⚠️ Volume fraco (permitido)")
            # NÃO BLOQUEIA

        return True
    
    def decide(self, decision):

        if not isinstance(decision, dict):
            print("❌ Decision inválida")
            return HOLD

        # 🔥 monta o pacote correto
        signal_data = {
            "signal": decision.get("signal"),
            "score": decision.get("score", 0),
            "probability": decision.get("probability", 0),
            "volume_spike": decision.get("volume_spike", False),
            "momentum": decision.get("momentum", False)
        }

        return self.evaluate(signal_data)