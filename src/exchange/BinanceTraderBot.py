from src.data.data_provider import get_klines
from src.utils.safe_api import safe_api_call
from src.utils.binance_filters import get_symbol_filters, adjust_to_step_size
from src.utils.binance_execution import validate_order
import pandas as pd
import datetime
import time

from src import main

class BinanceTraderBot:

    def __init__(self, symbol, client, config, risk_manager=None):

        self.symbol = symbol
        self.client = client
        self.config = config

        self.position_open = False
        self.entry_price = 0
        self.quantity = 0

        self.highest_price = 0
        self.last_trade_time = 0
        self.operation_code = symbol

        self.risk_manager = risk_manager
        
        self.is_running = False
        self.daily_profit = 0       
        

    # -----------------------------------------
    # 📊 DATA

    def get_data(self):
        return get_klines(self.client, self.symbol)


    # -----------------------------------------
    # 💰 BUY

    def buy(self, quantity):

        if self.position_open:
            print("⚠️ Já existe posição aberta")
            return None

        # -----------------------------------------
        # 💰 SALDO (SAFE API)

        try:
            balance_data = safe_api_call(
                self.client.get_asset_balance,
                asset="USDT"
            )

            balance = float(balance_data["free"])

            if balance < 5:
                print("💸 Saldo insuficiente")
                return None

        except Exception as e:
            print("❌ Erro ao verificar saldo:", e)
            return None

        # -----------------------------------------
        # ⏱️ PROTEÇÃO SPAM

        if time.time() - self.last_trade_time < 2:
            print("⚠️ Ordem muito rápida")
            return None

        # -----------------------------------------
        # 🔧 VALIDAÇÃO QTD

        if quantity is None:
            print("❌ BUY cancelado: quantity None")
            return None

        if not isinstance(quantity, (int, float)):
            print("❌ BUY cancelado: quantity inválido")
            return None

        if quantity <= 0:
            print("❌ BUY cancelado: quantity <= 0")
            return None

        quantity = float(quantity)
        quantity = round(quantity, 6)

        # -----------------------------------------
        # 🔧 AJUSTE BINANCE

        quantity = self._adjust_quantity(quantity)

        if quantity <= 0:
            print("❌ Quantity inválida após ajuste")
            return None
        # -----------------------------------------
        # 📈 PREÇO (ANTES DE VALIDAR)

        price = self.get_price()

        if not price or price <= 0:
            print("⚠️ Sem preço → cancelando BUY")
            return None
        
        # ----------------------------------------
        #VALIDAÇÃO BINANCE
        quantity, _, error = validate_order(
            self.client,
            self.symbol,
            quantity,
            price
        )

        if error:
            print(f"⚠️ Ordem inválida: {error}")
            return None

        if quantity <= 0:
            print("⚠️ Quantidade inválida")
            return None

        # -----------------------------------------
        # 🧾 ORDEM (SAFE API)

        try:
            order = safe_api_call(
                self.client.create_order,
                symbol=self.symbol,
                side="BUY",
                type="MARKET",
                quantity=quantity
            )

            if not order or order.get("status") not in ["FILLED", "PARTIALLY_FILLED"]:
                print("⚠️ Ordem não executada")
                return None

            executed_qty = float(order.get("executedQty", quantity))

            # -----------------------------------------
            # ✅ ATUALIZA ESTADO

            self.position_open = True
            fills = order.get("fills", [])
            if fills:
                price = float(fills[0]["price"])
            
            self.entry_price = price
            self.quantity = executed_qty
            self.highest_price = price
            self.last_trade_time = time.time()

            print(f"🚀 BUY {self.symbol} @ {price} | qty={executed_qty} | balance_used≈{executed_qty * price:.2f}")

            return order

        except Exception as e:
            print("❌ Erro no BUY:", e)
            return None
        
    # -----------------------------------------
    # 🔻 SELL

    def sell(self):

        if not self.position_open:
            print("⚠️ Nenhuma posição para vender")
            return None

        try:
            
            price = self.get_price()
            
            if price is None or price <= 0:
                print("⚠️ Preço inválido no SELL")
                return None
        
            quantity, _, error = validate_order(
                self.client,
                self.symbol,
                self.quantity,
                price
            )

            if error:
                print(f"⚠️ SELL inválido: {error}")
                return None

            order = safe_api_call(
                self.client.create_order,
                symbol=self.symbol,
                side="SELL",
                type="MARKET",
                quantity=quantity
            )
            
            if order and order.get("status") not in ["FILLED", "PARTIALLY_FILLED"]:
                print("⚠️ Ordem não executada")
                return None

            # 🔥 PREÇO REAL DA EXECUÇÃO
            exec_price = price  # preço inicial (fallback)

            fills = order.get("fills", [])
            if fills:
                exec_price = float(fills[0]["price"])

            entry = float(self.entry_price)

            # 🔥 CÁLCULO CORRETO
            profit = float((exec_price - entry) * quantity)
            
            print(f"💰 Execução real: {exec_price} | Entrada: {entry}")
            
            if price is None or price <= 0:
                print("⚠️ Preço inválido no SELL")
                return None

            if quantity <= 0:
                print("⚠️ Quantidade inválida no SELL")
                return None
            
            # 🔥 ATUALIZA LUCRO DIÁRIO
            self.daily_profit += profit

            # 🔥 SALVAR TRADE AQUI
            trade = {
                "time": str(datetime.datetime.now()),
                "symbol": self.symbol,
                "side": "SELL",
                "entry": entry,
                "exit": exec_price,
                "profit": profit
            }

            main.TRADE_HISTORY.append(trade)

            print(f"✅ TRADE SALVO: {trade}")

            # 🔥 ATUALIZA RISK MANAGER
            if self.risk_manager:
                self.risk_manager.register_trade(profit)

            print(f"🔻 SELL {self.symbol} @ {price} | qty={quantity} | PnL: {profit:.2f}")

            # reset posição
            self.position_open = False
            self.entry_price = 0
            self.quantity = 0
            self.highest_price = 0

            self.last_trade_time = time.time()

            return order

        except Exception as e:
            print("❌ Erro no SELL:", e)
            return None
    # -----------------------------------------
    # 📈 PRICE

    def get_price(self):

        # 🔥 1. tenta websocket (rápido)
        if hasattr(self, "price_stream"):
            price = self.price_stream.get_price(self.symbol)
            if price:
                return price

        # 🔥 2. fallback API (lento mas seguro)
        try:
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            return float(ticker["price"])
        except Exception as e:
            print("⚠️ fallback price erro:", e)
            return None
        
    # -----------------------------------------
    # ⏱️ COOLDOWN

    def can_trade(self):

        cooldown = self.config.get("TEMPO_ENTRE_TRADES", 60)

        if time.time() - self.last_trade_time < cooldown:
            print("⏱️ Aguardando cooldown")
            return False

        return True

    # -----------------------------------------
    # 🔄 TROCA DE ATIVO

    def set_symbol(self, symbol):
        
        if hasattr(self, "price_stream"):
            self.price_stream.start(symbol)

        if self.symbol == symbol:
            return

        if self.position_open:
            print("⚠️ Não pode trocar ativo com posição aberta")    
            return
        
        print(f"🔄 Mudando ativo: {self.symbol} → {symbol}")        

        self.symbol = symbol
        self.operation_code = symbol

        self.position_open = False
        self.entry_price = 0
        self.quantity = 0
        self.highest_price = 0

    # -----------------------------------------
    # 🌍 FILTRO GLOBAL (AGORA FUNCIONAL)

    def marketRiskFilter(self, data):

        spread = data.get("spread", 0)
        momentum = data.get("momentum", False)
        volume_spike = data.get("volume_spike", False)

        # 🚫 spread ruim (isso sim bloqueia)
        if spread > 0.003:
            print("🚫 Spread ruim")
            return False

        # ⚠️ momentum fraco (não bloqueia mais)
        if not momentum:
            print("⚠️ Sem momentum global")

        # ⚠️ volume fraco (não bloqueia)
        if not volume_spike:
            print("⚠️ Volume fraco")

        return True

    # -----------------------------------------
    # 🔧 AJUSTE DE QUANTIDADE

    def _adjust_quantity(self, qty):

        try:
            filters = get_symbol_filters(self.client, self.symbol)

            step = filters["stepSize"]
            min_qty = filters["minQty"]

            qty = adjust_to_step_size(qty, step)

            if qty < min_qty:
                print(f"⚠️ Qty menor que minQty ({min_qty})")
                return 0

            return qty

        except Exception as e:
            print("❌ Erro ao ajustar quantidade:", e)
            return 0
