from src.intelligence.market_condition import MarketConditionDetector
from src.strategies.vortex_strategy import vortex_rsi_volume_strategy
from src.strategies.rsi_strategy import getRsiTradeStrategy
from src.strategies.strategy_runner import rsi_strategy_wrapper  # 🔥 IMPORT CORRETO
from src.strategies.mean_reversion_strategy import mean_reversion_strategy
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
        self.market_detector = MarketConditionDetector()

    # -----------------------------------------
    # 🔁 CICLO ÚNICO

    def run_once(self):

        print("\n🚀 Novo ciclo")
        
        # 🔴 BLOQUEIO POR SEQUÊNCIA DE PERDAS
        if self.risk_manager.consecutive_losses >= self.config["RISK"].get("MAX_CONSECUTIVE_LOSSES", 3):
            print("🛑 Muitas perdas seguidas - pausando bot")
            return

        # 🛑 risco global
        if not self.risk_manager.can_trade():
            print("⛔ Bloqueado por risco")
            return

        # ⏱️ cooldown bot
        if not self.bot.can_trade():
            return

        # 🛑 limite diário
        max_trades = self.config["RISK"].get("MAX_TRADES_PER_DAY", 999)

        if self.trade_count_today >= max_trades:
            print("🛑 Limite diário de trades atingido")
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
        # 🧠 DETECTAR MERCADO

        market_condition = self.market_detector.detect(df)
        print(f"🧠 Market: {market_condition}")

        # -----------------------------------------
        # 🧠 ESCOLHER ESTRATÉGIA

        if market_condition == "TREND":
            strategy = vortex_rsi_volume_strategy

        elif market_condition == "NORMAL":
            strategy = rsi_strategy_wrapper

        elif market_condition == "SIDEWAYS":
            print("🔄 Mercado lateral → usando Mean Reversion")
            strategy = mean_reversion_strategy

        elif market_condition == "VOLATILE":
            strategy = vortex_rsi_volume_strategy  # depois você pode trocar por breakout

        else:
            print("⏸️ Mercado ruim, pulando")
            return

        # -----------------------------------------
        # 🧠 EXECUTAR ESTRATÉGIA

        decision = self.strategy_runner.execute(
            bot=self.bot,
            main_strategy=strategy,
            fallback_strategy=None,
            stock_data=df
        )

        # -----------------------------------------
        # 🛡️ NORMALIZAÇÃO

        if isinstance(decision, str):
            decision = {"signal": decision}

        if not isinstance(decision, dict):
            print(f"❌ Decision inválida: {decision}")
            return

        if not decision:
            return

        decision = {
            "signal": decision.get("action"),  # 🔥 CORRETO
            "score": decision.get("score", 0),
            "probability": decision.get("confidence", 0),  # 🔥 CORRETO
            "regime": decision.get("regime", "UNKNOWN"),
            "spread": decision.get("spread", 0),
            "volume_spike": decision.get("volume_spike", True),  # 🔥 libera
            "momentum": decision.get("momentum", True),          # 🔥 libera
            "orderflow": decision.get("orderflow", "BUY")        # 🔥 evita bloqueio
        }

        if not decision["signal"]:
            print("⚠️ Decision sem sinal")
            return

        # 🚫 filtro rápido
        if decision["probability"] < 0.3:
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
            spread=decision["spread"],
            volume_spike=decision["volume_spike"],
            momentum=decision["momentum"],
            orderflow=decision["orderflow"]
        )

        print(f"📊 {symbol} → {action}")

        if action == "HOLD":
            return

        # -----------------------------------------
        # 💰 EXECUÇÃO

        self.execute_trade(action)

        print(f"🧠 decision raw: {decision}")

    # -----------------------------------------
    # 💰 EXECUÇÃO

    def execute_trade(self, action):

        price = self.bot.get_price()

        if not price:
            print("⚠️ Preço inválido")
            return

        if action == "SELL" and self.bot.position_open:

            entry_price = getattr(self.bot, "entry_price", None)
            exit_price = price

            if entry_price:
                profit = (exit_price - entry_price) / entry_price
            else:
                profit = 0

            self.bot.sell()

            # 🔥 ATUALIZA PERDAS
            if profit < 0:
                self.risk_manager.register_trade(profit)
                print(f"❌ Loss consecutivo: {self.risk_manager.consecutive_losses}")
            else:
                self.risk_manager.consecutive_losses = 0
                print("✅ Reset perdas consecutivas")

            self.trade_count_today += 1
            return

        if action == "BUY" and not self.bot.position_open:

            # 🔥 RISCO POR TRADE (1%)
            balance = float(self.bot.client.get_asset_balance(asset="USDT")["free"])

            risk_per_trade = 0.01  # 1%
            risk_value = balance * risk_per_trade

            stop_loss_pct = self.config["STOP_LOSS_PERCENTAGE"] / 100

            position_size = risk_value / stop_loss_pct

             # trava max
            capital = min(position_size, balance * 0.05) 

            if capital <= 0:
                print("⚠️ Capital inválido")
                return

            qty = capital / price
            
            self.bot.buy(qty)

            # 🔥 SALVA PREÇO DE ENTRADA
            self.bot.entry_price = price

            self.trade_count_today += 1

    # -----------------------------------------
    # 🛡️ POSITION SIZE

    def get_position_size(self):

        try:
            balance = float(self.bot.client.get_asset_balance(asset="USDT")["free"])
        except Exception as e:
            print(f"❌ Erro ao obter saldo: {e}")
            return 0

        max_pct = self.config["RISK"].get("MAX_POSITION_PERCENT", 0.05)
        capital = balance * max_pct

        print(f"💰 Capital calculado: {capital:.2f}")

        return capital
    
    def check_break_even(self, entry_price, current_price):

        profit_pct = ((current_price - entry_price) / entry_price) * 100

        if profit_pct >= self.config["BREAK_EVEN"]["ACTIVATION"]:
            print("🔒 Break-even ativado")
            return entry_price

        return None
    
    def check_trailing(self, current_price, highest_price):

        trailing_pct = self.config["TRAILING"]["DISTANCE"]

        trailing_price = highest_price * (1 - trailing_pct / 100)

        return trailing_price