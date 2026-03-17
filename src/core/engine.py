from src.strategies.vortex_strategy import vortex_rsi_volume_strategy
import time

class TradingEngine:

    def __init__(self, bot, scanner, strategy_runner, decision_engine, config):

        self.bot = bot
        self.scanner = scanner
        self.strategy_runner = strategy_runner
        self.decision_engine = decision_engine
        self.config = config

        self.last_trade_time = 0
        self.trade_count_today = 0

    # -----------------------------------------
    # 🔁 CICLO ÚNICO (CORE DO BOT)

    def run_once(self):

        # -----------------------------------------
        # ⛔ RATE LIMIT / TEMPO ENTRE TRADES

        now = time.time()

        if now - self.last_trade_time < self.config["TEMPO_ENTRE_TRADES"]:
            return

        # -----------------------------------------
        # 🔍 SCANNER

        symbol = self.scanner()

        if not symbol:
            print("⚠️ Nenhum ativo encontrado")
            return

        self.bot.set_symbol(symbol)

        # -----------------------------------------
        # 📊 DADOS

        df = self.bot.get_data()

        if df is None or df.empty:
            print("⚠️ Sem dados")
            return

        # -----------------------------------------
        # 🧠 ESTRATÉGIA
        
        decision = self.strategy_runner.execute(
            bot=self.bot,
            main_strategy=vortex_rsi_volume_strategy,
            fallback_strategy=None,  # ou RSI simples depois
            stock_data=df
        )

        # 🛡️ NORMALIZAÇÃO CRÍTICA
        if isinstance(decision, str):
            decision = {
                "signal": decision,
                "score": 0,
                "probability": 0,
                "regime": "UNKNOWN",
                "spread": 0,
                "volume_spike": False,
                "momentum": False,
                "orderflow": "NEUTRAL"
            }

        if not isinstance(decision, dict):
            print(f"❌ Decision inválida: {decision}")
            return

        if not decision:
           return

        signal = decision.get("signal")

        if not signal:
            print("⚠️ Decision inválida")
            return

        # -----------------------------------------
        # 🎯 DECISÃO FINAL

        action = self.decision_engine.evaluate(
            bot=self,
            signal=decision["signal"],
            score=decision["score"],
            probability=decision["probability"],
            regime=decision["regime"],
            spread=decision.get("spread", 0),
            volume_spike=decision.get("volume_spike", False),
            momentum=decision.get("momentum", False),
            orderflow=decision.get("orderflow", "NEUTRAL")
        )

        print(f"📊 {symbol} → {action}")

        # -----------------------------------------
        # 💰 EXECUÇÃO

        self.execute_trade(action)

        print(f"🧠 decision raw: {decision} | tipo: {type(decision)}")

    # -----------------------------------------
    # 💰 EXECUÇÃO DE ORDENS

    def execute_trade(self, action):

        price = self.bot.get_price()

        # -----------------------------------------
        # 🔻 SELL

        if action == "SELL" and self.bot.position_open:
            self.bot.sell()
            self.last_trade_time = time.time()
            self.trade_count_today += 1
            return

        # -----------------------------------------
        # 🚀 BUY

        if action == "BUY" and not self.bot.position_open:

            capital = self.get_position_size(price)

            if capital <= 0:
                return

            self.bot.quantity = capital / price
            self.bot.buy(self.bot.quantity)

            self.last_trade_time = time.time()
            self.trade_count_today += 1

    # -----------------------------------------
    # 🛡️ POSITION SIZING

    def get_position_size(self, price):

        try:
            balance = float(self.bot.client.get_asset_balance(asset="USDT")["free"])
        except:
            return 0

        max_pct = self.config["RISK"]["MAX_POSITION_PERCENT"]

        capital = balance * max_pct

        return capital
