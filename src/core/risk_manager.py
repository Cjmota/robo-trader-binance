class RiskManager:

    def __init__(self, config):

        self.config = config

        self.daily_profit = 0
        self.daily_loss = 0
        self.consecutive_losses = 0

        self.trading_blocked = False

    # -----------------------------------------
    # 📊 REGISTRA RESULTADO

    def register_trade(self, profit):

        if profit > 0:
            self.daily_profit += profit
            self.consecutive_losses = 0
        else:
            self.daily_loss += abs(profit)
            self.consecutive_losses += 1

        self.check_limits()

    # -----------------------------------------
    # 🚫 VERIFICA LIMITES

    def check_limits(self):

        if self.daily_loss >= self.config["RISK"]["MAX_DAILY_LOSS"]:
            print("🛑 Stop diário atingido")
            self.trading_blocked = True

        if self.daily_profit >= self.config["RISK"]["DAILY_TARGET"]:
            print("🎯 Meta diária atingida")
            self.trading_blocked = True

        if self.consecutive_losses >= self.config["RISK"]["MAX_CONSECUTIVE_LOSSES"]:
            print("⚠️ Muitas perdas seguidas")
            self.trading_blocked = True

    # -----------------------------------------
    # ✅ PODE OPERAR?

    def can_trade(self):
        return not self.trading_blocked

    # -----------------------------------------
    # 📉 AJUSTE DE LOTE

    def adjust_position(self, base_value):

        reduction = min(self.consecutive_losses * 0.2, 0.6)

        adjusted = base_value * (1 - reduction)

        return adjusted
    