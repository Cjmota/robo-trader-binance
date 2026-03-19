class RiskManager:



    def __init__(self, config):

        self.config = config

        self.daily_profit = 0
        self.daily_loss = 0
        self.consecutive_losses = 0

        self.trading_blocked = False
        self.current_day = None
        
        self.consecutive_losses = 0 # 🔥 CONTROLE DE PERDAS

    # -----------------------------------------
    # 📊 RESET DIÁRIO

    def reset_daily(self):

        from datetime import datetime

        today = datetime.utcnow().date()

        if self.current_day != today:
            print("🔄 Reset diário de risco")
            self.daily_profit = 0
            self.daily_loss = 0
            self.consecutive_losses = 0
            self.trading_blocked = False
            self.current_day = today

    # -----------------------------------------
    # 📊 REGISTRA RESULTADO

    def register_trade(self, profit):

        self.reset_daily()

        if profit > 0:
            self.daily_profit += profit
            self.consecutive_losses = 0
        else:
            self.daily_loss += abs(profit)
            self.consecutive_losses += 1

        print(f"📊 PnL Dia → +{self.daily_profit:.2f} / -{self.daily_loss:.2f}")
        print(f"📉 Perdas consecutivas: {self.consecutive_losses}")

        self.check_limits()

    # -----------------------------------------
    # 🚫 VERIFICA LIMITES

    def check_limits(self):

        risk = self.config.get("RISK", {})

        max_loss = risk.get("MAX_DAILY_LOSS", 999999)
        daily_target = risk.get("DAILY_TARGET", 999999)
        max_losses = risk.get("MAX_CONSECUTIVE_LOSSES", 999)

        if self.daily_loss >= max_loss:
            print("🛑 Stop diário atingido")
            self.trading_blocked = True

        if self.daily_profit >= daily_target:
            print("🎯 Meta diária atingida")
            self.trading_blocked = True

        if self.consecutive_losses >= max_losses:
            print("⚠️ Muitas perdas seguidas")
            self.trading_blocked = True

    # -----------------------------------------
    # ✅ PODE OPERAR?

    def can_trade(self):

        if self.daily_loss <= -self.config["RISK"]["MAX_DAILY_LOSS"]:
            print("🛑 Stop diário atingido")
            return False

        if self.daily_profit >= self.config["RISK"]["DAILY_TARGET"]:
            print("🎯 Meta diária atingida")
            return False

        return True

    # -----------------------------------------
    # 📉 AJUSTE DE LOTE

    def adjust_position(self, base_value):

        reduction = min(self.consecutive_losses * 0.2, 0.6)

        adjusted = base_value * (1 - reduction)

        # 🔥 proteção contra lote mínimo
        min_value = self.config.get("RISK", {}).get("MIN_POSITION", base_value * 0.2)

        adjusted = max(adjusted, min_value)

        print(f"⚖️ Ajuste de posição: {adjusted:.2f}")

        return adjusted