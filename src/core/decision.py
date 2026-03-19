BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class DecisionEngine:

    def __init__(self, config=None):
        self.config = config or {}

    def evaluate(
        self,
        bot,
        signal,
        score,
        probability,
        regime,
        spread,
        volume_spike,
        momentum,
        orderflow
    ):
        #modo debug
        #return signal 

        print("\n🧠 DECISION ENGINE")

        # 🛡️ proteção contra None
        score = score or 0
        probability = probability or 0
        volume_spike = bool(volume_spike)

        # 🔹 pacote de dados
        market_data = {
            "spread": spread,
            "volume_spike": volume_spike,
            "momentum": momentum,
            "orderflow": orderflow,
            "regime": regime
        }

        # -----------------------------------------
        # 1️⃣ validação básica
        if signal not in [BUY, SELL]:
            print("⚠️ Sem sinal válido")
            return HOLD

        # -----------------------------------------
        # 2️⃣ filtro de risco global
        if not self.market_filter(bot, market_data):
            return HOLD

        # -----------------------------------------
        # 3️⃣ regime
        if not self.regime_filter(signal, regime, momentum, orderflow):
            return HOLD

        # -----------------------------------------
        # 4️⃣ qualidade
        if not self.quality_filter(score, probability, signal):
            return HOLD

        # -----------------------------------------
        # 5️⃣ fluxo
        if not self.flow_filter(signal, momentum, orderflow, volume_spike, score):
            return HOLD

        # -----------------------------------------
        # 6️⃣ spread dinâmico
        spread_limit = self.config.get("SCANNER", {}).get("SPREAD_LIMIT", 0.004)

        if spread > spread_limit:
            print(f"⚠️ Spread alto: {spread}")
            return HOLD

        # -----------------------------------------
        print(f"✅ TRADE APROVADO → {signal}")
        return signal

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

        # 🔥 corrige prob para SELL
        if signal == SELL:
            probability = 1 - probability

        print(f"📊 Score: {score} | Prob: {probability:.2f}")

        # 🚫 incoerência total
        if score < 0 and signal == BUY:
            print("⛔ Direção incoerente")
            return False

        if score > 0 and signal == SELL:
            print("⛔ Direção incoerente")
            return False

        # 🚫 score muito ruim
        if abs(score) < 0.05:
            print("⚠️ Score muito fraco")
            return False

        # 🚫 prob baixa
        if probability < 0.3:
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

        # -----------------------------------------
        if not volume_spike:
            print("⚠️ Volume fraco")

        return True
    
    def decide(self, decision):

        if not isinstance(decision, dict):
            print("❌ Decision inválida")
            return HOLD

        return self.evaluate(            
            bot=decision.get("bot"),
            signal=decision.get("signal"),
            score=decision.get("score"),
            probability=decision.get("probability"),
            regime=decision.get("regime"),
            spread=decision.get("spread", 0),
            volume_spike=decision.get("volume_spike", False),
            momentum=decision.get("momentum", False),
            orderflow=decision.get("orderflow", "NEUTRAL")
        )