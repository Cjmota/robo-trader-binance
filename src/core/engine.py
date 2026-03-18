from src.strategies.vortex_strategy import vortex_rsi_volume_strategy
import time

class TradingEngine:

    def __init__(self, bot, scanner, strategy_runner, decision_engine, config, risk_manager):

        self.bot = bot
        self.scanner = scanner
        self.strategy_runner = strategy_runner
        self.decision_engine = decision_engine
        self.config = config
        self.risk_manager = risk_manager
        self.trade_count_today = 0

    # -----------------------------------------
    # 🔁 CICLO ÚNICO (CORE DO BOT)

    def run_once(self):

        # 🛑 BLOQUEIO DE RISCO (COLOCA AQUI)
        if not self.risk_manager.can_trade():
            print("⛔ Bloqueado por risco")
            return
        
         # ⏱️ tempo / cooldown
        if not self.bot.can_trade():
            return

        # -----------------------------------------
        # ⛔ RATE LIMIT / TEMPO ENTRE TRADES

        now = time.time()

        if not self.bot.can_trade():
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

        # 🚫 FILTRO DE QUALIDADE (AQUI 🔥)
        if decision.get("probability", 0) < 0.3:
            print("🚫 Probabilidade baixa")
            return

        # -----------------------------------------
        # 🎯 DECISÃO FINAL

        action = self.decision_engine.evaluate(
            bot=self.bot,
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
            #self.last_trade_time = time.time()
            self.trade_count_today += 1
            return

        # -----------------------------------------
        # 🚀 BUY

        if action == "BUY" and not self.bot.position_open:

            base_capital = self.get_position_size(price)
            capital = self.risk_manager.adjust_position(base_capital)

            if capital <= 0:
                return

            self.bot.quantity = capital / price
            self.bot.buy(self.bot.quantity)

            #self.last_trade_time = time.time()
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
