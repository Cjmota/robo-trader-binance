import pandas as pd
import time

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

    # -----------------------------------------
    # 📊 DATA

    def get_data(self):

        try:
            interval = self.config.get("CANDLE_PERIOD", "5m")

            candles = self.client.get_klines(
                symbol=self.symbol,
                interval=interval,
                limit=100
            )

            df = pd.DataFrame(candles)

            df["close_price"] = pd.to_numeric(df[4])
            df["high_price"] = pd.to_numeric(df[2])
            df["low_price"] = pd.to_numeric(df[3])
            df["volume"] = pd.to_numeric(df[5])

            return df

        except Exception as e:
            print(f"❌ Erro ao obter dados: {e}")
            return None

    # -----------------------------------------
    # 💰 BUY

    def buy(self, quantity):

        if self.position_open:
            print("⚠️ Já existe posição aberta")
            return None
        
        try:
            balance = float(self.client.get_asset_balance(asset="USDT")["free"])
            if balance < 5:
                print("💸 Saldo insuficiente")
                return None
        except Exception as e:
            print("❌ Erro ao verificar saldo:", e)
            return None

        if time.time() - self.last_trade_time < 2:
            print("⚠️ Ordem muito rápida")
            return None
        
        quantity = self._adjust_quantity(quantity)
        
        if quantity <= 0:
            print("⚠️ Quantidade inválida")
            return None
        
        try:
            order = self.client.create_order(
                symbol=self.symbol,
                side="BUY",
                type="MARKET",
                quantity=quantity
            )
            
            if order and order.get("status") not in ["FILLED", "PARTIALLY_FILLED"]:
                print("⚠️ Ordem não executada")
                return None

            price = self.get_price()

            if price is None or price <= 0:
                print("⚠️ Preço inválido no BUY")
                return None

            executed_qty = float(order.get("executedQty", quantity))

            self.position_open = True
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
            quantity = self._adjust_quantity(self.quantity)

            order = self.client.create_order(
                symbol=self.symbol,
                side="SELL",
                type="MARKET",
                quantity=quantity
            )
            
            if order and order.get("status") not in ["FILLED", "PARTIALLY_FILLED"]:
                print("⚠️ Ordem não executada")
                return None

            price = self.get_price()
            
            if price is None or price <= 0:
                print("⚠️ Preço inválido no SELL")
                return None

            if quantity <= 0:
                print("⚠️ Quantidade inválida no SELL")
                return None

            profit = (price - self.entry_price) * self.quantity

            # 🔥 ATUALIZA RISK MANAGER
            if self.risk_manager:
                self.risk_manager.register_trade(profit)

            print(f"🔻 SELL {self.symbol} @ {price} | qty={self.quantity} | PnL: {profit:.2f}")
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

        try:
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            return float(ticker["price"])
        except Exception as e:
            print(f"❌ Erro ao obter preço: {e}")
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

        # 🔥 simplificado (ideal: usar stepSize da Binance)
        return round(qty, 5)
