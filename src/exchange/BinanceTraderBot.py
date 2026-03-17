import pandas as pd

class BinanceTraderBot:

    def __init__(self, symbol, client, config):

        self.symbol = symbol
        self.client = client
        self.config = config

        self.position_open = False
        self.entry_price = 0
        self.quantity = 0

        self.trailing_price = 0
        self.highest_price = 0

        self.last_trade_time = 0

    # -----------------------------------------
    # 📊 DATA

    def get_data(self):

        candles = self.client.get_klines(
            symbol=self.symbol,
            interval="5m",
            limit=100
        )

        df = pd.DataFrame(candles)

        df["close"] = pd.to_numeric(df[4])
        df["volume"] = pd.to_numeric(df[5])

        return df

    # -----------------------------------------
    # 💰 BUY

    def buy(self, quantity):

        order = self.client.create_order(
            symbol=self.symbol,
            side="BUY",
            type="MARKET",
            quantity=quantity
        )

        self.position_open = True
        self.entry_price = self.get_price()

        print(f"🚀 BUY {self.symbol}")

        return order

    # -----------------------------------------
    # 🔻 SELL

    def sell(self):

        order = self.client.create_order(
            symbol=self.symbol,
            side="SELL",
            type="MARKET",
            quantity=self.quantity
        )

        self.position_open = False

        print(f"🔻 SELL {self.symbol}")

        return order

    # -----------------------------------------
    # 📈 PRICE

    def get_price(self):

        ticker = self.client.get_symbol_ticker(symbol=self.symbol)
        return float(ticker["price"])

    # -----------------------------------------
    # 🧠 RISK

    def trailing_stop(self, price):

        if not self.position_open:
            return False

        if price > self.highest_price:
            self.highest_price = price

        trail = self.highest_price * (1 - 0.01)

        if price < trail:
            print("🔴 Trailing acionado")
            self.sell()
            return True

        return False

    def set_symbol(self, symbol):

        if self.symbol == symbol:
            return  # evita reset desnecessário

        print(f"🔄 Mudando ativo: {self.symbol} → {symbol}")

        self.symbol = symbol

        # reset estado
        self.position_open = False
        self.entry_price = 0
        self.quantity = 0

        self.trailing_price = 0
        self.highest_price = 0          
            
