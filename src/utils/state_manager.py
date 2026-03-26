import json
from datetime import datetime
import os

STATE_FILE = "state.json"

class StateManager:
    def __init__(self):
        self.trades_today = 0
        self.last_reset_day = None
        self.limit_warned = False
        self.load()

    def load(self):
        if not os.path.exists(STATE_FILE):
            return

        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)

                self.trades_today = data.get("trades_today", 0)

                last_day = data.get("last_reset_day")
                if last_day:
                    self.last_reset_day = datetime.fromisoformat(last_day).date()

        except Exception as e:
            print(f"⚠️ Erro ao carregar state: {e}")

    def save(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({
                    "trades_today": self.trades_today,
                    "last_reset_day": str(self.last_reset_day)
                }, f)
        except Exception as e:
            print(f"⚠️ Erro ao salvar state: {e}")

    def check_reset(self):
        today = datetime.utcnow().date()

        if self.last_reset_day != today:
            print("🔄 Reset diário de trades")
            self.trades_today = 0
            self.last_reset_day = today
            self.limit_warned = False
            self.save()

    def can_trade(self, max_trades):
        if self.trades_today >= max_trades:
            if not self.limit_warned:
                print("🛑 Limite diário de trades atingido")
                self.limit_warned = True
            return False

        self.limit_warned = False
        return True

    def register_trade(self):
        self.trades_today += 1
        self.save()