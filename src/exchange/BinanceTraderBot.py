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

        candles = self.client.get_klines(
            symbol=self.symbol,
            interval="5m",
            limit=100
        )

        df = pd.DataFrame(candles)

        df["close_price"] = pd.to_numeric(df[4])
        df["high_price"] = pd.to_numeric(df[2])
        df["low_price"] = pd.to_numeric(df[3])
        df["volume"] = pd.to_numeric(df[5])

        return df

    # -----------------------------------------
    # 💰 BUY

    def buy(self, quantity):

        if self.position_open:
            print("⚠️ Já existe posição aberta")
            return None

        try:
            order = self.client.create_order(
                symbol=self.symbol,
                side="BUY",
                type="MARKET",
                quantity=quantity
            )

            price = self.get_price()

            self.position_open = True
            self.entry_price = price
            self.quantity = quantity
            self.highest_price = price
            self.last_trade_time = time.time()

            print(f"🚀 BUY {self.symbol} @ {price}")

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
            order = self.client.create_order(
                symbol=self.symbol,
                side="SELL",
                type="MARKET",
                quantity=self.quantity
            )

            price = self.get_price()

            print(f"🔻 SELL {self.symbol} @ {price}")

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

        ticker = self.client.get_symbol_ticker(symbol=self.symbol)
        return float(ticker["price"])

    # -----------------------------------------
    # 🧠 TRAILING STOP

    def trailing_stop(self, price):

        if not self.position_open:
            return False

        if price > self.highest_price:
            self.highest_price = price

        trail_percent = self.config.get("TRAILING_PERCENT", 0.01)
        trail_price = self.highest_price * (1 - trail_percent)

        if price < trail_price:
            print("🔴 Trailing acionado")
            self.sell()
            return True

        return False

    # -----------------------------------------
    # ⏱️ PROTEÇÃO TEMPO

    def can_trade(self):

        cooldown = self.config.get("TRADE_COOLDOWN", 10)

        return time.time() - self.last_trade_time > cooldown
    
    def set_symbol(self, symbol):

        if self.symbol == symbol:
            return

        print(f"🔄 Mudando ativo: {self.symbol} → {symbol}")

        self.symbol = symbol
        self.operation_code = symbol  # 🔥 compatibilidade

        # reset estado
        self.position_open = False
        self.entry_price = 0
        self.quantity = 0
        self.trailing_price = 0
        self.highest_price = 0