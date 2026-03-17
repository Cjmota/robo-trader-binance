import time
import threading


class TradingEngine:

    def __init__(
        self,
        bot,
        scanner,
        strategy_runner,
        decision_engine,
        config
    ):

        self.bot = bot
        self.scanner = scanner
        self.strategy_runner = strategy_runner
        self.decision_engine = decision_engine

        self.config = config

        self.running = False

        self.loop_interval = config.get("ENGINE", {}).get("LOOP_INTERVAL", 10)

        self.current_symbol = None

    # -----------------------------------------
    # 🚀 START

    def start(self):

        from src import main  # importa o controle do Flask

        print("🚀 Engine iniciada")

        while main.BOT_RUNNING:

            try:
                self.execute_cycle()  # ou o nome do seu método principal

            except Exception as e:
                print("Erro no loop:", e)

            time.sleep(2)

    # -----------------------------------------
    # 🧠 CICLO PRINCIPAL

    def run_cycle(self):

        print("\n🔄 Novo ciclo")

        # -------------------------------------
        # 1️⃣ SCANNER

        symbol = self.scanner()

        if not symbol:
            print("⚠️ Nenhum ativo encontrado")
            return

        self.current_symbol = symbol
        self.bot.set_symbol(symbol)

        print(f"🎯 Ativo selecionado: {symbol}")

        # -------------------------------------
        # 2️⃣ DATA

        data = self.bot.get_data()

        if data is None or data.empty:
            print("⚠️ Sem dados")
            return

        # -------------------------------------
        # 3️⃣ REGIME (simples por enquanto)

        regime = self.detect_regime(data)

        # -------------------------------------
        # 4️⃣ STRATEGY

        signal = self.strategy_runner.execute(
            bot=self.bot,
            main_strategy=self.bot.main_strategy,
            fallback_strategy=self.bot.fallback_strategy,
            stock_data=data,
            main_strategy_args=self.bot.main_strategy_args,
            fallback_strategy_args=self.bot.fallback_strategy_args,
        )

        if signal not in ["BUY", "SELL"]:
            print("⏸️ HOLD")
            return

        # -------------------------------------
        # 5️⃣ SCORE (simples - pode melhorar depois)

        score = self.calculate_score(data)
        probability = self.calculate_probability(score)

        # -------------------------------------
        # 6️⃣ DECISION ENGINE

        decision = self.decision_engine.evaluate(
            bot=self.bot,
            signal=signal,
            score=score,
            probability=probability,
            regime=regime,
            spread=0.001,
            volume_spike=True,
            momentum=True,
            orderflow="BUY" if signal == "BUY" else "SELL"
        )

        # -------------------------------------
        # 7️⃣ EXECUÇÃO

        if decision == "BUY" and not self.bot.position_open:

            quantity = self.calculate_quantity()

            self.bot.buy(quantity)

        elif decision == "SELL" and self.bot.position_open:

            self.bot.sell()

        # -------------------------------------
        # 8️⃣ RISK (sempre rodar)

        price = self.bot.get_price()

        self.bot.trailing_stop(price)

    # -----------------------------------------
    # 📊 REGIME

    def detect_regime(self, data):

        volatility = data["close"].pct_change().std()

        if volatility < 0.002:
            return "SIDEWAYS"
        else:
            return "TREND"

    # -----------------------------------------
    # 📊 SCORE

    def calculate_score(self, data):

        last = data["close"].iloc[-1]
        prev = data["close"].iloc[-2]

        change = (last - prev) / prev

        score = 5

        if change > 0:
            score += 2

        return score

    # -----------------------------------------
    # 📊 PROBABILIDADE

    def calculate_probability(self, score):

        return min(score / 10, 1.0)

    # -----------------------------------------
    # 💰 QUANTIDADE

    def calculate_quantity(self):

        price = self.bot.get_price()

        capital = 50  # fixo por enquanto

        return round(capital / price, 6)