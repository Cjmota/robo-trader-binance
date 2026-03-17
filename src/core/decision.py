BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


class DecisionEngine:

    def __init__(self, config=None):
        self.config = config or {}

    # -----------------------------------------
    # 🧠 FUNÇÃO PRINCIPAL
    # -----------------------------------------
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

        print("\n🧠 DECISION ENGINE")

        # -----------------------------------------
        # 1️⃣ validação básica
        if signal not in [BUY, SELL]:
            print("⚠️ Sem sinal válido")
            return HOLD

        # -----------------------------------------
        # 2️⃣ filtro de risco global
        if not self.market_filter(bot):
            return HOLD

        # -----------------------------------------
        # 3️⃣ filtro de regime
        if not self.regime_filter(signal, regime):
            return HOLD

        # -----------------------------------------
        # 4️⃣ qualidade do trade
        if not self.quality_filter(score, probability):
            return HOLD

        # -----------------------------------------
        # 5️⃣ confirmação de fluxo
        if not self.flow_filter(signal, momentum, orderflow):
            return HOLD

        # -----------------------------------------
        # 6️⃣ spread / liquidez
        if spread > 0.004:
            print("⚠️ Spread alto")
            return HOLD

        # -----------------------------------------
        # 7️⃣ validação final
        print(f"✅ TRADE APROVADO → {signal}")

        return signal

    # -----------------------------------------
    # 🔒 FILTROS
    # -----------------------------------------

    def market_filter(self, bot):

        if not bot.marketRiskFilter():
            print("🌍 Mercado global ruim")
            return False

        return True

    def regime_filter(self, signal, regime):

        if regime == "SIDEWAYS":
            print("⏸️ Mercado lateral")
            return False

        if regime == "TREND" and signal == SELL:
            print("⚠️ Contra tendência")
            return False

        return True

    def quality_filter(self, score, probability):

        print(f"📊 Score: {score} | Prob: {probability:.2f}")

        if score < 5:
            print("⛔ Score baixo")
            return False

        if probability < 0.45:
            print("⛔ Probabilidade baixa")
            return False

        return True

    def flow_filter(self, signal, momentum, orderflow):

        if signal == BUY:

            if not momentum:
                print("⚠️ Sem momentum")
                return False

            if orderflow != "BUY":
                print("⚠️ Orderflow não confirma")
                return False

        if signal == SELL:

            if orderflow != "SELL":
                print("⚠️ Venda sem pressão")
                return False

        return True
    
    def decide(self, decision):

        return self.evaluate(
            bot=decision.get("bot"),
            signal=decision.get("signal"),
            score=decision.get("score", 0),
            probability=decision.get("probability", 0),
            regime=decision.get("regime", "UNKNOWN"),
            spread=decision.get("spread", 0),
            volume_spike=decision.get("volume_spike", False),
            momentum=decision.get("momentum", False),
            orderflow=decision.get("orderflow", "NEUTRAL")
        )