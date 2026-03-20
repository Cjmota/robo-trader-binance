from binance import ThreadedWebsocketManager

class PriceStream:

    def __init__(self, api_key, api_secret):
        self.twm = ThreadedWebsocketManager(api_key, api_secret)
        self.twm.start()
        self.prices = {}

    def start(self, symbol):

        def handle(msg):

            if msg.get('e') == 'error':
                print("❌ WS erro:", msg)
                return

            self.prices[symbol] = float(msg['c'])

        self.twm.start_symbol_ticker_socket(
            callback=handle,
            symbol=symbol
        )

    def get_price(self, symbol):
        return self.prices.get(symbol)