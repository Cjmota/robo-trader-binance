from src.intelligence.market_condition import MarketConditionDetector
from src.strategies.vortex_strategy import vortex_rsi_volume_strategy
from src.strategies.rsi_strategy import getRsiTradeStrategy
from src.strategies.strategy_runner import rsi_strategy_wrapper  # 🔥 IMPORT CORRETO
from src.strategies.mean_reversion_strategy import mean_reversion_strategy
from src.utils.helpers import to_native
from src.utils.safe_api import safe_api_call
from src import main
import time
import math
import datetime

def get_rsi_safe(df):
    if "rsi" not in df.columns:
        return None
    return df["rsi"].iloc[-1]

import math

def adjust_qty_to_step(qty, step_size):
    precision = int(round(-math.log(step_size, 10), 0))
    return float(round(math.floor(qty / step_size) * step_size, precision)) 

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
    def run_once(self):
        
        symbol = getattr(self.bot, "symbol", None)

        if not symbol:
            print("❌ Symbol inválido")
            return
    
        balance_data = safe_api_call(
            self.bot.client.get_asset_balance,
            asset="USDT"
        )

        if self.trade_count_today == 0 and not hasattr(self, "dust_cleaned"):
            self.auto_clear_dust()
            self.dust_cleaned = True

        if not balance_data or float(balance_data["free"]) < 5:
            print("💤 Sem capital suficiente — aguardando")
            return
        
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

        new_symbol = self.scanner()

        if new_symbol and new_symbol != self.bot.symbol:

            if not self.bot.position_open:

                if not hasattr(self, "last_symbol_change"):
                    self.last_symbol_change = 0

                if time.time() - self.last_symbol_change > 120:
                    print(f"🔄 Mudando ativo: {self.bot.symbol} → {new_symbol}")
                    self.bot.set_symbol(new_symbol)
                    self.last_symbol_change = time.time()


        symbol = self.bot.symbol
        df = self.bot.get_data()

        if df is None or df.empty:
            print("⚠️ Sem dados")
            return

        rsi = get_rsi_safe(df)
        
        # 🔥 PADRONIZA COLUNA CLOSE
        if "close" not in df.columns:
            if "close_price" in df.columns:
                df["close"] = df["close_price"]
            elif "Close" in df.columns:
                df["close"] = df["Close"]
            else:
                print("❌ Sem coluna close")
                return

        # 🚫 FILTRO DE VOLATILIDADE (ROBUSTO)

        volatility_series = df["close"].pct_change().rolling(10).std()

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
        ma50 = float(df["close"].rolling(50).mean().iloc[-1])
        price = float(df["close"].iloc[-1])

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
        
        original_signal = None
        
        # -----------------------------------------
        # 🔥 FALLBACK INTELIGENTE (CORRETO)

        if raw_decision is None or raw_decision == "HOLD":
                        
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
        
        # 🔥 CONFLITO CONTEXTUAL (PRO)

        if decision["signal"] != decision["orderflow"]:

            if market_condition == "SIDEWAYS":
                # mean reversion pode ir contra fluxo
                print("⚠️ Conflito ignorado (mean reversion)")
            
            elif decision["score"] < 0.65:
                print("🚫 Conflito fraco")
                return
        
        # depois de normalizar
        if decision["signal"] != "HOLD":
            if decision["score"] == 0 and decision["probability"] > 0:
                print("⚙️ Score ajustado pelo probability")
                decision["score"] = decision["probability"]

        print(f"🧠 NORMALIZED: {decision}")

        #print(f"🧠 NORMALIZED: {decision}")        
        print(f"🧠 FINAL → {decision['signal']} | prob={decision['probability']:.2f}")   
        
        # 🔥 BLOQUEIO INTELIGENTE (POR CONTEXTO)

        if market_condition != "SIDEWAYS":

            if decision["signal"] == "BUY" and trend == "DOWN":
                if decision["score"] < 0.5:
                    print("🚫 BUY contra tendência")
                    return

            if decision["signal"] == "SELL" and trend == "UP":
                if decision["score"] < 0.5:
                    print("🚫 SELL contra tendência")
                    return
        
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
            print("🧊 HOLD — sem trade")
            return
                
       
                    
      
        # -----------------------------------------
        # 🧠 CONFLUÊNCIA PROFISSIONAL

        confluence = 0

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

        if rsi is None:
            factors -= 1

        base_score = decision["score"]

        confluence_score = confluence / max(factors, 1)

        score = 0

        score = (
            decision["probability"] * 0.5 +
            (0.2 if decision["momentum"] else 0) +
            (0.2 if decision["volume_spike"] else 0) +
            (0.3 if decision["signal"] == "BUY" and trend == "UP" else 0) +
            (0.3 if decision["signal"] == "SELL" and trend == "DOWN" else 0)
        )
            
        raw_score = (base_score * 0.3) + (score * 0.5) + (confluence_score * 0.2)

        # 🔥 CORREÇÃO CRÍTICA (ANTI-SCORE NEGATIVO)
        decision["score"] = max(min(raw_score, 1), 0)
        
        print(f"📊 DEBUG → signal={decision['signal']} | prob={decision['probability']:.2f} | score={decision['score']:.2f}")
        
        # 🔥 FILTRO FINAL SIMPLES

        if decision["score"] < 0.15 and not decision.get("force_trade"):
            print("⚠️ Entrada muito fraca")
            return
        
        # 🔒 Só força trade em caso MUITO forte
        if decision["signal"] == "HOLD" and decision.get("force_trade"):
            if decision["score"] > 0.65:
                decision["signal"] = "BUY" if trend == "UP" else "SELL"

        if market_condition != "SIDEWAYS":
            if not decision["momentum"] and decision["score"] < 0.2 and not decision.get("force_trade"):
                print("⚠️ Momentum fraco")
                return
        
        # 🚫 NÃO VENDE SEM POSIÇÃO (SPOT)
        if decision["signal"] == "SELL" and not self.bot.position_open:
            print("🚫 Ignorando SELL sem posição")
            return
        
        # -----------------------------------------
        # 🔥 PROBABILIDADE INTELIGENTE

        decision["probability"] = min(
            decision["probability"] * 0.5 + decision["score"] * 0.5,
            1.0
        )
        
        if market_condition == "SIDEWAYS":
            decision["probability"] *= 1.1
            decision["probability"] = min(decision["probability"], 1.0)

        # -----------------------------------------
        # 🧠 PRIORIDADE DO TRADE

        priority = 0

        priority += decision["probability"]
        priority += decision["score"]

        if decision["volume_spike"]:
            priority += 0.3

        decision["priority"] = priority

    

        # -----------------------------------------
        # 🎯 DECISÃO FINAL

        # 🚫 FILTRO FINAL DE QUALIDADE (CORRETO)

        action = decision["signal"]

        print(f"📊 {symbol} → {action}")

        if action == "HOLD":
            return

        perf = self.get_symbol_performance(symbol)

        if perf["winrate"] < 0.45 and len(perf["last_results"]) >= 8:
            print(f"🚫 {symbol} ignorado antes da entrada")
            return

        # -----------------------------------------
        # 💰 EXECUÇÃO
        
        if hasattr(self, "last_signal"):
            if self.last_signal == decision["signal"] and self.bot.position_open:
                print("🔁 Sinal repetido ignorado")
                return

        self.last_signal = decision["signal"]

        self.execute_trade(action, decision, df, symbol)

        print(f"🧠 decision raw: {decision}")

    def execute_trade(self, action, decision, df, symbol):

        # 🔥 CRÍTICO — SEM ISSO VAI QUEBRAR
        lot = self.bot.get_lot_size(symbol)

        if not lot:
            print("❌ Erro ao obter LOT_SIZE")
            return

        step_size = float(lot.get("stepSize", 0.0001))
        min_qty = float(lot.get("minQty", 0))
        min_notional = float(lot.get("minNotional", 5))
        
        balance_data = safe_api_call(
            self.bot.client.get_asset_balance,
            asset="USDT"
        )
        
        if not balance_data or "free" not in balance_data:
            print("❌ Erro ao obter saldo")
            return

        balance = float(balance_data["free"])        
        capital = 0

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
            profit_pct = (price - entry) / entry * 100
            
            # 🔥 STOP RÁPIDO (anti travamento)
            if profit_pct < -1.0:
                print("🛑 Stop rápido (anti-travamento)")
                self.update_performance(symbol, profit_pct)
                self.bot.sell()
                self.trade_count_today += 1
                return
            
            if not hasattr(self.bot, "partial_taken"):
                self.bot.partial_taken = False

            if profit_pct >= 1.2 and not self.bot.partial_taken:
                print("💰 Realizando parcial (50%)")
                
                qty = adjust_qty_to_step(self.bot.quantity * 0.5, step_size)

                if qty < lot["minQty"]:
                    print("⚠️ Parcial abaixo do mínimo")
                    return

                print(f"💰 Vendendo parcial: {qty}")
                self.bot.sell(qty)

                self.bot.partial_taken = True
                return
            
            # -----------------------------------------
            # 🔥 BREAK EVEN REAL (COM TAXA)

            if profit_pct > 0.6:
                if price <= entry * 1.006:
                    print("🟡 Break Even (real)")
                    self.bot.sell()
                    return
            
            # TRAILING
            if price > self.bot.highest_price:
                self.bot.highest_price = price

            profit_pct = (price - entry) / entry * 100
            
            # 🔥 TRAILING PROFISSIONAL

            if profit_pct > 4:
                trailing_dist = 0.15
            elif profit_pct > 3:
                trailing_dist = 0.2
            elif profit_pct > 2:
                trailing_dist = 0.3
            elif profit_pct > 1:
                trailing_dist = 0.5
            else:
                trailing_dist = 0.8  
            
            trailing_price = self.bot.highest_price * (1 - trailing_dist / 100) 

            if price < trailing_price:
                print("📉 Trailing Stop")
                                
                self.update_performance(symbol, profit_pct)
                
                self.bot.sell()
                self.trade_count_today += 1
                return           
            
            # 🔥 SAÍDA POR FRAQUEZA

            if decision["momentum"] is False and profit_pct > 0.5:
                print("📉 Saída por fraqueza (momentum)")
                self.bot.sell()
                return 
            
            # STOP LOSS           
            
            if profit_pct < -1.5:
                print("🛑 Stop inteligente")
                self.update_performance(symbol, profit_pct)
                self.bot.sell()
                self.trade_count_today += 1
                return
        
            # ⏰ tempo máximo em posição
            max_hold_time = 60 * 30  # 30 minutos

            if hasattr(self.bot, "entry_time"):
                if time.time() - self.bot.entry_time > max_hold_time:
                    print("⏰ Saindo por tempo (capital preso)")
                    self.update_performance(symbol, profit_pct)
                    self.bot.sell()
                    self.trade_count_today += 1
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
        if decision["signal"] == "BUY" and last_close < prev_close and decision["score"] < 0.6:
            print("🚫 Candle contra entrada (ajustado)")
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
        # -------------------BUY----------------------
        # 💰 POSITION SIZE

        if not balance_data or "free" not in balance_data:
            print("❌ Erro ao obter saldo")
            return

        balance = float(balance_data["free"])

        if balance < 5:
            print("⚠️ Saldo insuficiente (<5 USDT)")
            return

        # 🔥 RISCO ADAPTATIVO
        perf = self.get_symbol_performance(symbol)
        winrate = perf["winrate"]

        if winrate > 0.65:
            risk_pct = 0.02
        elif winrate < 0.4:
            risk_pct = 0.005
        else:
            risk_pct = 0.01

        # -----------------------------------------
        # 🚀 INTELIGÊNCIA (ITEM 5)

        capital = balance * risk_pct

        score = self.get_symbol_score(symbol)

        if score > 0.7:
            capital *= 1.3
            print(f"🚀 Aumentando lote ({symbol} forte)")

        elif score < 0.4:
            capital *= 0.7
            print(f"⚠️ Reduzindo lote ({symbol} fraca)")

        # -----------------------------------------
        # 🚫 CAPITAL MÍNIMO

        capital = max(capital, 3)

        # -----------------------------------------
        # 🔢 CALCULA QTY

        capital = capital * 0.99
        qty = capital / price

        if qty <= 0:
            print("❌ qty inválido")
            return

        # -----------------------------------------
        # 🔥 LOT (AGORA SIM)

        if not lot:
            print(f"⚠️ Não foi possível obter LOT_SIZE para {symbol}")
            return

        qty = adjust_qty_to_step(qty, step_size)

        if qty <= 0:
            print("❌ qty inválido após ajuste")
            return

        # -----------------------------------------
        # 🔍 VALIDAÇÃO FINAL  
        
        notional = qty * price

        if notional < min_notional:
            print(f"⚠️ Ordem abaixo do mínimo ({min_notional}) → {notional}")
            return

        # -----------------------------------------
        # 🧪 DEBUG

        print(f"""
        🧪 DEBUG FINAL
        symbol={symbol}
        price={price}
        balance={balance}
        capital={capital}
        qty={qty}
        notional={notional}
        score={score}
        """)

        # -----------------------------------------
        # 🚀 EXECUTA

        self.bot.buy(qty)
        self.bot.entry_time = time.time()
        self.trade_count_today += 1
        

        print(f"🟢 BUY REAL EXECUTADO | qty={qty}")
                    
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

        # mantém últimos 20 trades
        perf["last_results"] = perf["last_results"][-20:]

        total = len(perf["last_results"])

        if total > 0:
            perf["winrate"] = sum(perf["last_results"]) / total

        # 🔥 SCORE INTELIGENTE (NOVA PARTE)
        avg = (perf["wins"] - perf["losses"]) / max(total, 1)

        perf["score"] = (perf["winrate"] * 0.7) + (avg * 0.3)

        print(f"📊 {symbol} | Winrate: {perf['winrate']:.2f} | Score: {perf['score']:.2f}")
        
    def get_symbol_performance(self, symbol):

        if symbol not in self.performance_by_symbol:
            self.performance_by_symbol[symbol] = {
                "wins": 0,
                "losses": 0,
                "last_results": [],
                "winrate": 0.5
            }

        return self.performance_by_symbol[symbol]
    
    def get_symbol_score(self, symbol):
        perf = self.get_symbol_performance(symbol)

        total = len(perf["last_results"])

        if total < 5:
            return 0.5  # neutro

        winrate = perf["winrate"]

        streak = sum(perf["last_results"][-3:])  # últimos 3 trades

        score = (winrate * 0.7) + (streak / 3 * 0.3)

        return score
    
    def get_top_symbols(self, top_n=3):
        ranking = []

        for symbol in self.performance_by_symbol:
            score = self.get_symbol_score(symbol)
            ranking.append((symbol, score))

        ranking.sort(key=lambda x: x[1], reverse=True)

        return [s[0] for s in ranking[:top_n]]
    
    def auto_clear_dust(self):
        account = self.bot.client.get_account()

        for asset in account["balances"]:
            free = float(asset["free"])
            asset_name = asset["asset"]

            if asset_name == "USDT":
                continue

            if free > 0:
                symbol = asset_name + "USDT"

                try:
                    print(f"🧹 Limpando {asset_name}")

                    self.bot.set_symbol(symbol)
                    self.bot.quantity = free  # 🔥 AJUSTE AQUI
                    self.bot.sell()

                except Exception as e:
                    print(f"Erro ao limpar {asset_name}: {e}")