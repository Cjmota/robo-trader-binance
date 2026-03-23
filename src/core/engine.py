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

        self.performance_by_symbol = {}

    # -----------------------------------------
    # 🔁 CICLO ÚNICO

    def run_once(self):
        
        today = datetime.date.today()

        if not hasattr(self, "last_trade_day"):
            self.last_trade_day = today

        if self.last_trade_day != today:
            print("🔄 Reset diário")
            self.trade_count_today = 0
            self.last_trade_day = today

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

        # 🚫 FILTRO DE VOLATILIDADE (ROBUSTO)

        volatility_series = df["close_price"].pct_change().rolling(10).std()

        if volatility_series.isna().iloc[-1]:
            print("⚠️ Volatilidade inválida (dados insuficientes)")
            return

        volatility = float(volatility_series.iloc[-1])

        if volatility > 0.03:
            print(f"⚠️ Volatilidade extrema: {volatility:.4f}")
            return

        if volatility < 0.001:
            print(f"🚫 Mercado morto: {volatility:.4f}")
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

        raw_decision = self.strategy_runner.execute(
            bot=self.bot,
            main_strategy=strategy,
            fallback_strategy=None,
            stock_data=df
        )
        
        # -----------------------------------------
        # 🔥 FALLBACK INTELIGENTE (CORRETO)

        if raw_decision is None or raw_decision == "HOLD":

            if "rsi" in df.columns:
                rsi = df["rsi"].iloc[-1]

                if rsi > 60:
                    raw_decision = "SELL"
                    print("🔴 Fallback SELL (RSI alto)")

                elif rsi < 40:
                    raw_decision = "BUY"
                    print("🟢 Fallback BUY (RSI baixo)")
        
        # 🔥 EXTRAI SINAL REAL DA ESTRATÉGIA
        original_signal = None

        if isinstance(raw_decision, str):
            original_signal = raw_decision

        elif isinstance(raw_decision, dict):
            original_signal = (
                raw_decision.get("action")
                or raw_decision.get("signal")
            )
        
        # 🔥 limpa numpy na raiz
        decision = self.decision_engine.evaluate(raw_decision)
        
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

        probability = decision.get("probability", decision.get("confidence", 0))

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
        if decision["signal"] != "HOLD":
            if decision["score"] == 0 and decision["probability"] > 0:
                print("⚙️ Score ajustado pelo probability")
                decision["score"] = decision["probability"]

        print(f"🧠 NORMALIZED: {decision}")

        #print(f"🧠 NORMALIZED: {decision}")        
        print(f"🧠 FINAL → {decision['signal']} | prob={decision['probability']:.2f}")   
        
        # -----------------------------------------
        # -----------------------------------------
        # 🔥 RECUPERAR SINAL DA ESTRATÉGIA (ROBUSTO)

        if decision["signal"] == "HOLD" and original_signal and original_signal != "HOLD":

            recovered_signal = None

            # caso venha string direta
            if isinstance(original_signal, str):
                recovered_signal = original_signal

            # caso venha dict
            elif isinstance(original_signal, dict):
                recovered_signal = (
                    original_signal.get("action")
                    or original_signal.get("signal")
                )

            if recovered_signal and recovered_signal != "HOLD":
                decision["signal"] = recovered_signal
                decision["probability"] = 0.4
                decision["score"] = 0.4
                
                decision["force_trade"] = True

                print(f"♻️ Recuperando sinal da estratégia: {recovered_signal}")     

        # 🔍 DEBUG PROFISSIONAL (ANTES DOS FILTROS)
                
        # 🚀 MOSTRA OPORTUNIDADE (ANTES DOS FILTROS)
        if decision["signal"] != "HOLD":
            print(f"🚀 POSSÍVEL TRADE → {decision}")

        # 🚫 FILTRO DE VOLUME (MELHORIA 3)
        if market_condition == "TREND":
            if not decision["volume_spike"] and decision["probability"] < 0.4:
                return

        if not decision["signal"]:
            print("⚠️ Decision sem sinal")
            return

        # 🚫 filtro rápido
        min_prob = 0.35

        if market_condition == "TREND":
            min_prob = 0.3

        if market_condition == "SIDEWAYS":
            min_prob = 0.30

        if decision["probability"] < min_prob and not decision.get("force_trade"):
            print(f"⚠️ Prob baixa ({decision['probability']:.2f}) → reduzindo força")
            decision["score"] *= 0.5

        # 🚫 FILTRO DE SPREAD
        if decision["spread"] > 0.003:
            print("🚫 Spread alto")
            return

        if decision["signal"] == "HOLD":
            print("⚠️ HOLD original — tentando extrair oportunidade")
            
        
            
        # -----------------------------------------
        # 🔄 FORÇAR ENTRADA EM LATERAL / HOLD

        if decision["signal"] == "HOLD" and not decision.get("force_trade"):
            rsi = df["rsi"].iloc[-1]

            if rsi < 42:
                decision["signal"] = "BUY"
                decision["probability"] = 0.35
                print("🟢 HOLD → BUY (RSI baixo)")

            elif rsi > 58:
                decision["signal"] = "SELL"
                decision["probability"] = 0.35
                print("🔴 HOLD → SELL (RSI alto)")

        # 🔥 BOOST PARA HOLD QUEBRADO
        if decision["signal"] != "HOLD" and decision["score"] == 0:
            decision["score"] = 0.3
            print("⚙️ Score mínimo aplicado (HOLD break)")
            
        if decision["signal"] != "HOLD" and decision["probability"] < 0.3:
            decision["probability"] = 0.3

        # -----------------------------------------
        # 🧠 CONFLUÊNCIA PROFISSIONAL

        confluence = 0

        # RSI (se existir)
        if "rsi" in df.columns:
            rsi = df["rsi"].iloc[-1]
            
            if decision["signal"] == "BUY" and rsi < 35:
                confluence += 1
                
            if decision["signal"] == "SELL" and rsi > 65:
                confluence += 1

        # Tendência
        if decision["signal"] == "BUY" and trend == "UP":
            confluence += 1

        if decision["signal"] == "SELL" and trend == "DOWN":
            confluence += 1

        # Volume
        if decision["volume_spike"]:
            confluence += 1

        # Momentum
        if decision["momentum"]:
            confluence += 1

        # -----------------------------------------
        # 🔥 SCORE REAL

        factors = 4

        if "rsi" not in df.columns:
            factors -= 1

        base_score = decision["score"]

        decision["score"] = confluence / max(factors, 1)

        # 🔥 FILTRO DE QUALIDADE PROFISSIONAL
        # 🧠 SCORE INTELIGENTE

        score = 0

        score += decision["probability"]

        if decision["momentum"]:
            score += 0.2

        if decision["volume_spike"]:
            score += 0.2

        if decision["signal"] == "BUY" and trend == "UP":
            score += 0.3

        if decision["signal"] == "SELL" and trend == "DOWN":
            score += 0.3
                   
        decision["score"] = (base_score * 0.3) + (score * 0.7)
        
        print(f"📊 DEBUG → signal={decision['signal']} | prob={decision['probability']:.2f} | score={decision['score']:.2f}")
        
        # 🔥 DESTRAVAR HOLD COM SCORE (CRÍTICO)

        if decision["signal"] == "HOLD":

            if decision["score"] > 0.5 and trend == "UP":
                decision["signal"] = "BUY"
                decision["force_trade"] = True
                print("🔥 HOLD → BUY (score forte)")

            elif decision["score"] < 0.3 and trend == "DOWN":
                decision["signal"] = "SELL"
                decision["force_trade"] = True
                print("🔥 HOLD → SELL (score forte)")
        
        if decision["score"] < 0.1:
            print("⚠️ Score baixo, mas permitido")

        if not decision["momentum"] and decision["probability"] < 0.25:
            print("⚠️ Sem momentum forte(ajustado)")
            return
        
        # 🚫 NÃO VENDE SEM POSIÇÃO (SPOT)
        if decision["signal"] == "SELL" and not self.bot.position_open:
            print("🚫 Ignorando SELL sem posição")
            return
        
        # -----------------------------------------
        # 🔥 PROBABILIDADE INTELIGENTE

        prob = decision["probability"]

        prob += decision["score"] * 0.35

        decision["probability"] = min(prob, 1.0)
        
        if market_condition == "SIDEWAYS":
            decision["probability"] *= 1.2

        # -----------------------------------------
        # 🧠 PRIORIDADE DO TRADE

        priority = 0

        priority += decision["probability"]
        priority += decision["score"]

        if decision["volume_spike"]:
            priority += 0.3

        decision["priority"] = priority

        if decision["priority"] < 0.35 and not decision.get("force_trade"):
            print("⚠️ Trade fraco")
            return

        # -----------------------------------------
        # 🎯 DECISÃO FINAL

        action = decision["signal"]

        print(f"📊 {symbol} → {action}")

        if action == "HOLD":
            return

        # -----------------------------------------
        # 💰 EXECUÇÃO

        self.execute_trade(action, decision, df, symbol)

        print(f"🧠 decision raw: {decision}")

    # -----------------------------------------
    # 💰 EXECUÇÃO

    def execute_trade(self, action, decision, df, symbol):

        # 🔥 GARANTE CLOSE NO EXECUTOR
        if "close" not in df.columns:

            if "close_price" in df.columns:
                df["close"] = df["close_price"]

            elif "Close" in df.columns:
                df["close"] = df["Close"]

            else:
                print("❌ ERRO: coluna close não encontrada no execute_trade")
                print(df.columns)
                return    

        # 🔥 PREÇO (CORRETO)
        price = self.bot.get_price()

        if price is None:
            print("⚠️ Preço None")
            return

        try:
            price = float(price)
        except Exception:
            print("❌ Preço inválido:", price)
            return

        if price <= 0:
            print("❌ Preço inválido (<=0):", price)
            return

        # -----------------------------------------
        # 🔥 GERENCIAMENTO DE POSIÇÃO

        if self.bot.position_open:

            entry = float(self.bot.entry_price)
            profit_pct = float((price - entry) / entry * 100)
            
            # -----------------------------------------
            # 🟡 BREAK EVEN (PROTEÇÃO DE LUCRO)

            if self.check_break_even(entry, price):
                if price <= entry * 1.003:
                    print("🟡 Break Even acionado")
                    
                    self.update_performance(symbol, profit_pct)
                    
                    self.bot.sell()
                    self.trade_count_today += 1
                    return

            # STOP LOSS
            if profit_pct <= -self.config["STOP_LOSS_PERCENTAGE"]:
                print("🛑 Stop Loss")
                
                self.update_performance(symbol, profit_pct)
                
                self.bot.sell()
                self.trade_count_today += 1
                return

            # TRAILING
            if price > self.bot.highest_price:
                self.bot.highest_price = price

            profit_pct = (price - entry) / entry * 100
            if profit_pct > 2:
                trailing_dist = 0.3
            elif profit_pct > 1:
                trailing_dist = 0.5
            else:
                trailing_dist = 1.0
                
            trailing_price = self.bot.highest_price * (1 - trailing_dist / 100)

            if price < trailing_price:
                print("📉 Trailing Stop")
                                
                self.update_performance(symbol, profit_pct)
                
                self.bot.sell()
                self.trade_count_today += 1
                return

        # -----------------------------------------
        # 🚫 BLOQUEIO SPOT (ESSENCIAL)

        if action == "SELL" and not self.bot.position_open:
            print("🚫 Ignorando SELL sem posição")
            return

        # -----------------------------------------
        # 🔻 SELL

        if action == "SELL" and self.bot.position_open:

            entry = float(self.bot.entry_price)
            profit_pct = (price - entry) / entry * 100

            self.update_performance(symbol, profit_pct)

            print("🔴 Fechando posição")
            self.bot.sell()
            self.trade_count_today += 1
            return

        # -----------------------------------------
        # 🧠 CONFIRMAÇÃO PROFISSIONAL

        if len(df) < 3:
            print("⚠️ Dados insuficientes")
            return

        ma20 = df["close"].rolling(20).mean().iloc[-1]

        last_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]

        # 🔥 1. Candle favorável
        if decision["signal"] == "BUY" and last_close < prev_close:
            print("🚫 Candle contra entrada")
            return

        # 🔥 2. Anti-FOMO
        distance = (last_close - ma20) / ma20

        perf = self.get_symbol_performance(symbol)
        winrate = perf["winrate"]

        # ajuste adaptativo por moeda
        if winrate > 0.6:
            decision["probability"] *= 1.1
            decision["probability"] = min(decision["probability"], 1.0)
            print(f"🟢 {symbol} forte")

        elif winrate < 0.4:
            decision["probability"] *= 0.85
            decision["probability"] = max(decision["probability"], 0.05)
            print(f"🔴 {symbol} fraco")

        if winrate < 0.3 and len(perf["last_results"]) > 10:
            print(f"🚫 Ignorando {symbol} (ruim)")
            return

        # -----------------------------------------
        # 🔺 BUY (FILTROS)
        
        # evita topo extremo
        if decision["signal"] == "BUY":
            if distance > 0.025:
                if decision["probability"] > 0.75:
                    print("⚠️ Rompimento forte permitido")
                else:
                    print("🚫 Muito esticado")
                    return
        
        cooldown = 60

        if decision["score"] > 0.7:
            cooldown = 30  # entra mais rápido em trade forte

        if time.time() - self.bot.last_trade_time < cooldown:
            print("⏱️ Evitando overtrade")
            return

        strong_entry = decision["score"] > 0.7
        
        if not strong_entry:
            if decision["probability"] < 0.35 and decision["score"] < 0.3:
                print("🚫 Entrada fraca")
                return
            
        last3 = df["close"].iloc[-3:]

        if decision["score"] < 0.25:
            print("🚫 Score muito baixo")
            return

        if action == "BUY":
            if last3.iloc[-1] > last3.iloc[-2] or decision["volume_spike"] or decision["momentum"]:
                print("📈 Micro tendência confirmada")
            else:
                if decision["probability"] < 0.6:
                    print("🚫 Timing fraco")
                    return

        if action == "BUY":

            if self.bot.position_open:
                print("⚠️ Já está em posição")
                return

            # candle filtro
            last_close = df["close"].iloc[-1]
            prev_close = df["close"].iloc[-2]

            # -----------------------------------------
            # 💰 POSITION SIZE

            balance_data = safe_api_call(
                self.bot.client.get_asset_balance,
                asset="USDT"
            )
            
            perf = self.get_symbol_performance(symbol)
            winrate = perf["winrate"]

            if winrate > 0.6:
                risk_pct = 0.015
            elif winrate < 0.4:
                risk_pct = 0.005
            else:
                risk_pct = 0.01

            # -----------------------------------------
            # 💰 POSITION SIZE PROFISSIONAL

            if not balance_data or "free" not in balance_data:
                print("❌ Erro ao obter saldo")
                return

            balance = float(balance_data["free"])

            risk_amount = balance * risk_pct

            # stop estimado (1%)
            stop_distance = 0.01

            capital = risk_amount / stop_distance

            # limite de segurança
            capital = min(capital, balance * 0.2)

            if capital < 2:
                print("⚠️ Capital muito baixo")
                return

            # -----------------------------------------
            # 💰 CALCULAR QUANTIDADE (ROBUSTO)
            
            try:
                qty = capital / price
                qty = float(qty)  # 🔥 FORÇA FLOAT
            except Exception as e:
                print("❌ Erro cálculo qty:", e)
                return

            # 🚫 validação básica
            if qty is None or qty <= 0:
                print("❌ Quantidade inválida:", qty)
                return

            # -----------------------------------------
            # 🚫 CAPITAL MÍNIMO (BINANCE)
            
            if capital < 5:
                print("⚠️ Capital insuficiente (<5 USDT)")
                return
            
            # -----------------------------------------
            # 🚫 QTY MÍNIMA

            if qty < 0.0001:
                print("⚠️ Qty muito pequena")
                return

            # -----------------------------------------
            # 🔧 AJUSTE DE PRECISÃO (ANTI-ERRO BINANCE)

            qty = round(qty, 6)
            
            # -----------------------------------------
            # 🧪 DEBUG PROFISSIONAL

            print(f"""
            🧪 DEBUG ORDER
            symbol={symbol}
            price={price}
            balance={balance}
            capital={capital}
            qty={qty}
            """)

            print(f"🟢 BUY EXECUTADO | qty={qty}")

            # -----------------------------------------
            # 🚀 EXECUÇÃO
            
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
    
    def update_performance(self, symbol, profit_pct):

        perf = self.get_symbol_performance(symbol)

        if profit_pct > 0:
            perf["wins"] += 1
            perf["last_results"].append(1)
        else:
            perf["losses"] += 1
            perf["last_results"].append(0)

        perf["last_results"] = perf["last_results"][-20:]

        total = len(perf["last_results"])

        if total > 0:
            perf["winrate"] = sum(perf["last_results"]) / total

        print(f"📊 {symbol} Winrate: {perf['winrate']:.2f}")
        
    def get_symbol_performance(self, symbol):

        if symbol not in self.performance_by_symbol:
            self.performance_by_symbol[symbol] = {
                "wins": 0,
                "losses": 0,
                "last_results": [],
                "winrate": 0.5
            }

        return self.performance_by_symbol[symbol]