from src.intelligence.market_condition import MarketConditionDetector
from src.strategies.vortex_strategy import vortex_rsi_volume_strategy
from src.strategies.rsi_strategy import getRsiTradeStrategy
from src.strategies.strategy_runner import rsi_strategy_wrapper  # 🔥 IMPORT CORRETO
from src.strategies.mean_reversion_strategy import mean_reversion_strategy
from src.utils.helpers import to_native
from src.utils.safe_api import safe_api_call
from src import main
import time
import datetime

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

        # 🔥 FILTRO GLOBAL SIMPLES
        ma50 = float(df["close_price"].rolling(50).mean().iloc[-1])
        price = float(df["close_price"].iloc[-1])

        trend = "UP" if price > ma50 else "DOWN"

        print(f"📈 Tendência: {trend}")

        # -----------------------------------------
        # 🧠 EXECUTAR ESTRATÉGIA

        decision = self.strategy_runner.execute(
            bot=self.bot,
            main_strategy=strategy,
            fallback_strategy=None,
            stock_data=df
        )
        
        # 🔥 limpa numpy na raiz
        decision = {k: to_native(v) for k, v in decision.items()}
        
        # 🔥 GARANTE FORMATO LIMPO
        if isinstance(decision.get("action"), dict):
            decision = decision["action"]

        if isinstance(decision.get("signal"), dict):
            decision = decision["signal"]
        
        #print(f"🧠 RAW DECISION: {decision}")

        # -----------------------------------------
        # 🛡️ NORMALIZAÇÃO

        if isinstance(decision, str):
            decision = {"action": decision, "confidence": 1}

        if not isinstance(decision, dict):
            print(f"❌ Decision inválida: {decision}")
            return

        if not decision:
            return

        if decision.get("confidence") and decision.get("confidence") > 0:
            decision["probability"] = decision["confidence"]

        signal = decision.get("action") or decision.get("signal") or "HOLD"

        if isinstance(signal, dict):
            signal = signal.get("action")

        probability = decision.get("probability") or decision.get("confidence", 0)

        if isinstance(probability, dict):
            probability = probability.get("confidence", 0)

        decision = {
            "signal": signal,
            "score": float(decision.get("score", 0)),
            "probability": float(probability),
            "regime": str(decision.get("regime", "UNKNOWN")),
            "spread": float(decision.get("spread", 0)),
            "volume_spike": bool(decision.get("volume_spike", True)),
            "momentum": bool(decision.get("momentum", True)),
            "orderflow": str(decision.get("orderflow", "BUY"))
        }
        
        # depois de normalizar
        if decision["score"] == 0 and decision["probability"] > 0:
            print("⚙️ Score ajustado pelo probability")
            decision["score"] = decision["probability"]

        print(f"🧠 NORMALIZED: {decision}")

        #print(f"🧠 NORMALIZED: {decision}")        
        print(f"🧠 FINAL → {decision['signal']} | prob={decision['probability']:.2f}")

        # 🔍 DEBUG PROFISSIONAL (ANTES DOS FILTROS)
        print(f"📊 DEBUG → signal={decision['signal']} | prob={decision['probability']:.2f} | score={decision['score']:.2f}")

        # 🚀 MOSTRA OPORTUNIDADE (ANTES DOS FILTROS)
        if decision["signal"] != "HOLD":
            print(f"🚀 POSSÍVEL TRADE → {decision}")

        # 🚫 FILTRO DE VOLUME (MELHORIA 3)
        if not decision["volume_spike"] and decision["probability"] < 0.4:
            print("🚫 Volume fraco + baixa confiança")
            return

        if not decision["signal"]:
            print("⚠️ Decision sem sinal")
            return

        # 🚫 filtro rápido
        if decision["probability"] < 0.4:
            print("🚫 Probabilidade baixa")
            return

        if decision["signal"] == "HOLD":
            return

        # 🔥 FILTRO DE QUALIDADE PROFISSIONAL
        if decision["score"] < 0.2:
            print("⚠️ Score fraco")
            return

        if not decision["momentum"] and decision["probability"] < 0.5:
            print("⚠️ Sem momentum forte")
            return
        
        # 🚫 NÃO VENDE SEM POSIÇÃO (SPOT)
        if decision["signal"] == "SELL" and not self.bot.position_open:
            print("🚫 Ignorando SELL sem posição")
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

        self.execute_trade(action, decision)

        print(f"🧠 decision raw: {decision}")

    # -----------------------------------------
    # 💰 EXECUÇÃO

    def execute_trade(self, action, decision):

        price = float(price)

        if not price:
            print("⚠️ Sem preço")
            return

        price = float(price)

        # -----------------------------------------
        # 🔥 GERENCIAMENTO DE POSIÇÃO

        if self.bot.position_open:

            entry = float(self.bot.entry_price)
            profit_pct = float((price - entry) / entry * 100)

            # STOP LOSS
            if profit_pct <= -self.config["STOP_LOSS_PERCENTAGE"]:
                print("🛑 Stop Loss")
                self.bot.sell()
                self.trade_count_today += 1
                return

            # BREAK EVEN
            be_cfg = self.config.get("BREAK_EVEN", {})
            be_activation = be_cfg.get("ACTIVATION", 1.0)

            if profit_pct >= be_activation and price <= entry:
                print("🔒 Break-even")
                self.bot.sell()
                self.trade_count_today += 1
                return

            # TRAILING
            tr_cfg = self.config.get("TRAILING", {})
            trailing_dist = tr_cfg.get("DISTANCE", 1.0)

            if price > self.bot.highest_price:
                self.bot.highest_price = price

            trailing_price = self.bot.highest_price * (1 - trailing_dist / 100)

            if price < trailing_price:
                print("📉 Trailing Stop")
                self.bot.sell()
                self.trade_count_today += 1
                return

        # -----------------------------------------
        # 🔻 SELL

        if action == "SELL" and self.bot.position_open:

            self.bot.sell()
            self.trade_count_today += 1

            print(f"📉 Perdas consecutivas: {self.risk_manager.consecutive_losses}")
            return

        # -----------------------------------------
        # 🔺 BUY

        if decision["probability"] < 0.45:
            print("🚫 Probabilidade insuficiente para BUY")
            return

        if action == "BUY" and not self.bot.position_open:

            price = self.bot.get_price()

            if not price:
                print("⚠️ Sem preço → cancelando BUY")
                return

            price = float(price)

            balance_data = safe_api_call(
                self.bot.client.get_asset_balance,
                asset="USDT"
            )

            balance = float(balance_data["free"])

            risk_per_trade = 0.005
            risk_value = balance * risk_per_trade

            stop_loss_pct = self.config["STOP_LOSS_PERCENTAGE"] / 100

            if stop_loss_pct <= 0:
                print("⚠️ Stop loss inválido")
                return

            position_size = risk_value / stop_loss_pct
            capital = min(position_size, balance * 0.05)

            if capital <= 0:
                print("⚠️ Capital inválido")
                return

            qty = float(capital / price)

            self.bot.buy(qty)

            self.trade_count_today += 1
                    
    # -----------------------------------------
    # 🛡️ POSITION SIZE

    def get_position_size(self):

        try:
            balance_data = safe_api_call(
                self.bot.client.get_asset_balance,
                asset="USDT"
            )
            balance = float(balance_data["free"])
            
        except Exception as e:
            print(f"❌ Erro ao obter saldo: {e}")
            return 0

        max_pct = self.config["RISK"].get("MAX_POSITION_PERCENT", 0.05)
        capital = float(balance * max_pct)

        print(f"💰 Capital calculado: {capital:.2f}")

        return capital
    
    def check_break_even(self, entry_price, current_price):

        profit_pct = float((current_price - entry_price) / entry_price * 100)

        be_cfg = self.config.get("BREAK_EVEN", {})
        be_activation = be_cfg.get("ACTIVATION", 1.0)

        if profit_pct >= be_activation:
            return True

        return False
        
    
    def check_trailing(self, current_price, highest_price):

        trailing_pct = self.config["TRAILING"]["DISTANCE"]

        trailing_price = highest_price * (1 - trailing_pct / 100)

        return trailing_price