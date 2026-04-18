# fmt: off
import os
import time
from datetime import datetime
import logging
import math

from dotenv import load_dotenv
import pandas as pd
from binance.client import Client
from binance.enums import *
from binance.enums import SIDE_SELL, ORDER_TYPE_STOP_LOSS_LIMIT
from binance.exceptions import BinanceAPIException

from src.modules.BinanceClient import BinanceClient
from src.modules.TraderOrder import TraderOrder
from src.modules.Logger import *

from src.modules.StrategyRunner import StrategyRunner


from src.strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from src.strategies.moving_average import getMovingAverageTradeStrategy

from src.indicators import Indicators

from src.state import bot_status

from src.telegram import send_telegram

from src.state import bot_control
from src.state import bot_control, lock

from src.state import best_asset

from src.strategies.vortex_strategy import getVortexTradeStrategy
from src.strategies.rsi_strategy import getRsiTradeStrategy

# fmt: on


load_dotenv()
api_key = os.getenv("BINANCE_API_KEY")
secret_key = os.getenv("BINANCE_SECRET_KEY")

GLOBAL_MANAGER = {
    "max_positions": 2,
    "min_score": 2,
}

# ------------------------------------------------------------------

# Classe Principal
class BinanceTraderBot:

    # --------------------------------------------------------------
    # Parâmetros da classe sem valor inicial
    last_trade_decision = None  # Última decisão de posição (False = Vender | True = Comprar)
    last_buy_price = 0  # Último valor de ordem de COMPRA executado
    last_sell_price = 0  # Ùltimo valor de ordem de VENDA executada
    open_orders = []
    # Valor que já foi executado e que será descontado da quantidade,
    # caso uma ordem não seja completamente executada
    partial_quantity_discount = 0

    tick_size: float
    step_size: float
    take_profit_index = 0

    # Construtor
    def __init__(
        self,
        stock_code,
        operation_code,
        traded_quantity,
        traded_percentage,
        candle_period,
        time_to_trade=30 * 60,
        delay_after_order=60 * 60,
        acceptable_loss_percentage=0.5,
        stop_loss_percentage=3.5,
        fallback_activated=True,
        take_profit_at_percentage=[],
        take_profit_amount_percentage=[],
        main_strategy=None,
        main_strategy_args=None,
        fallback_strategy=None,
        fallback_strategy_args=None,
        portfolio=None
    ):

        print("------------------------------------------------")
        print("🤖 Robo Trader iniciando...")

        # fmt: off

        self.stock_code = stock_code
        self.operation_code = operation_code
        self.traded_quantity = traded_quantity
        self.traded_percentage = traded_percentage
        self.candle_period = candle_period

        self.fallback_activated = fallback_activated
        self.acceptable_loss_percentage = acceptable_loss_percentage / 100
        self.stop_loss_percentage = stop_loss_percentage / 100

        # ✅ BUG 3 — Salva o stop loss original para poder restaurar depois
        self.initial_stop_loss_percentage = stop_loss_percentage / 100

        self.take_profit_at_percentage = take_profit_at_percentage
        self.take_profit_amount_percentage = take_profit_amount_percentage

        self.main_strategy = main_strategy
        self.main_strategy_args = main_strategy_args
        self.fallback_strategy = fallback_strategy
        self.fallback_strategy_args = fallback_strategy_args

        self.time_to_trade = time_to_trade
        self.delay_after_order = delay_after_order
        self.time_to_sleep = time_to_trade

        self.client_binance = BinanceClient(
            api_key, secret_key, sync=True, sync_interval=30000, verbose=False
        )

        self.setStepSizeAndTickSize()

        self.initial_balance_position = 0

        self.min_trade_usdt = 10

        self.daily_loss = 0
        self.daily_start_balance = 0

        self.last_reset_day = datetime.now().date()

        self.portfolio = portfolio
        
        self.stuck_counter = 0
        
        self.partial_done = False

        # fmt: on

    def isBought(self):
        return self.actual_trade_position

    def _reset_position_state(self):
        self.take_profit_index = 0
        self.partial_done = False
        self.stuck_counter = 0
        self.initial_balance_position = 0
        self.stop_loss_percentage = self.initial_stop_loss_percentage

    def updateAllData(self, verbose=False):
        try:

            today = datetime.now().date()

            if today != self.last_reset_day:
                print("🔄 Reset diário")
                self.daily_start_balance = self.getUSDTBalance()
                self.daily_loss = 0
                self.last_reset_day = today

            self.account_data = self.getUpdatedAccountData()
            self.last_stock_account_balance = self.getLastStockAccountBalance()
            self.actual_trade_position = self.getActualTradePosition()
            self.stock_data = self.getStockData()
            self.open_orders = self.getOpenOrders()
            self.last_buy_price = self.getLastBuyPrice(verbose)
            self.last_sell_price = self.getLastSellPrice(verbose)
            self.actual_trade_position = self.getActualTradePosition()

            if self.daily_start_balance == 0:
                self.daily_start_balance = self.getUSDTBalance()

            current_balance = self.getUSDTBalance()

            if self.daily_start_balance > 0:
                self.daily_loss = (self.daily_start_balance - current_balance) / self.daily_start_balance

        except BinanceAPIException as e:
            print(f"🚫 Erro Binance: {e}")
            time.sleep(5)
            return
        except Exception as e:
            print(f"🔥 Erro geral: {e}")
            time.sleep(5)
            return

    def getUpdatedAccountData(self):
        return self.client_binance.get_account()

    def getLastStockAccountBalance(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                free = float(stock["free"])
                locked = float(stock["locked"])
                return free + locked
        return 0.0

    def should_update_order(self, new_price, old_price, threshold=0.003):
        try:
            return abs(new_price - old_price) / old_price > threshold
        except Exception as e:
            print(f"Erro should_update_order: {e}")
            return True

    def getActualTradePosition(self):
        """
        Considera comprado apenas se posição tiver valor real em USDT.
        ✅ BUG 2 — Ao detectar posição VENDIDA, chama _reset_position_state()
        """
        try:
            if not hasattr(self, "stock_data") or self.stock_data is None:
                return False

            qty = self.last_stock_account_balance

            if qty <= 0:
                # ✅ BUG 2 + BUG 3 — Posição confirmada como vendida: reseta estado
                self._reset_position_state()
                return False

            price = self.stock_data["close_price"].iloc[-1]
            value_usdt = qty * price

            print(f"📦 {self.operation_code} posição: {qty} | Valor: {value_usdt:.2f} USDT")

            is_bought = value_usdt >= 5

            if not is_bought:
                # ✅ BUG 2 + BUG 3 — Valor abaixo do mínimo: também considera vendido
                self._reset_position_state()

            return is_bought

        except Exception as e:
            print(f"Erro posição atual {self.operation_code}: {e}")
            return False

    def getStockData(self):

        candles = self.client_binance.get_klines(
            symbol=self.operation_code,
            interval=self.candle_period,
            limit=1000,
        )

        prices = pd.DataFrame(candles)

        prices.columns = [
            "open_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "-",
        ]

        prices = prices[
            [
                "close_price",
                "open_time",
                "open_price",
                "high_price",
                "low_price",
                "volume",
            ]
        ]

        prices["close_price"] = pd.to_numeric(prices["close_price"], errors="coerce")
        prices["open_price"] = pd.to_numeric(prices["open_price"], errors="coerce")
        prices["high_price"] = pd.to_numeric(prices["high_price"], errors="coerce")
        prices["low_price"] = pd.to_numeric(prices["low_price"], errors="coerce")
        prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce")

        prices["open_time"] = pd.to_datetime(prices["open_time"], unit="ms").dt.tz_localize("UTC")
        prices["open_time"] = prices["open_time"].dt.tz_convert("America/Sao_Paulo")

        return prices

    def getLastBuyPrice(self, verbose=False):
        try:
            all_orders = self.client_binance.get_all_orders(symbol=self.operation_code, limit=100)
            executed_buy_orders = [o for o in all_orders if o["side"] == "BUY" and o["status"] == "FILLED"]

            if executed_buy_orders:
                last_executed_order = sorted(executed_buy_orders, key=lambda x: x["time"], reverse=True)[0]
                last_buy_price = float(last_executed_order["cummulativeQuoteQty"]) / float(last_executed_order["executedQty"])
                datetime_transact = datetime.utcfromtimestamp(last_executed_order["time"] / 1000).strftime("(%H:%M:%S) %d-%m-%Y")
                if verbose:
                    print(f"\nÚltima ordem de COMPRA executada para {self.operation_code}:")
                    print(f" - Data: {datetime_transact} | Preço: {self.adjust_to_step(last_buy_price, self.tick_size, as_string=True)}")
                return last_buy_price
            else:
                if verbose:
                    print(f"Não há ordens de COMPRA executadas para {self.operation_code}.")
                return 0.0

        except Exception as e:
            if verbose:
                print(f"Erro ao verificar a última ordem de COMPRA: {e}")
            return 0.0

    def getLastSellPrice(self, verbose=False):
        try:
            all_orders = self.client_binance.get_all_orders(symbol=self.operation_code, limit=100)
            executed_sell_orders = [o for o in all_orders if o["side"] == "SELL" and o["status"] == "FILLED"]

            if executed_sell_orders:
                last_executed_order = sorted(executed_sell_orders, key=lambda x: x["time"], reverse=True)[0]
                last_sell_price = float(last_executed_order["cummulativeQuoteQty"]) / float(last_executed_order["executedQty"])
                datetime_transact = datetime.utcfromtimestamp(last_executed_order["time"] / 1000).strftime("(%H:%M:%S) %d-%m-%Y")
                if verbose:
                    print(f"Última ordem de VENDA executada para {self.operation_code}:")
                    print(f" - Data: {datetime_transact} | Preço: {self.adjust_to_step(last_sell_price, self.tick_size, as_string=True)}")
                return last_sell_price
            else:
                if verbose:
                    print(f"Não há ordens de VENDA executadas para {self.operation_code}.")
                return 0.0

        except Exception as e:
            if verbose:
                print(f"Erro ao verificar a última ordem de VENDA: {e}")
            return 0.0

    def getTimestamp(self):
        try:
            if not hasattr(self, "time_offset") or self.time_offset is None:
                server_time = self.client_binance.get_server_time()["serverTime"]
                local_time = int(time.time() * 1000)
                self.time_offset = server_time - local_time
            adjusted_timestamp = int(time.time() * 1000) + self.time_offset
            return adjusted_timestamp
        except Exception as e:
            print(f"Erro ao ajustar o timestamp: {e}")
            return int(time.time() * 1000)

    def setStepSizeAndTickSize(self):
        symbol_info = self.client_binance.get_symbol_info(self.operation_code)
        price_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "PRICE_FILTER")
        self.tick_size = float(price_filter["tickSize"])
        lot_size_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "LOT_SIZE")
        self.step_size = float(lot_size_filter["stepSize"])

    def adjust_to_step(self, value, step, as_string=False):
        if step <= 0:
            raise ValueError("O valor de 'step' deve ser maior que zero.")
        decimal_places = (max(0, abs(int(math.floor(math.log10(step))))) if step < 1 else 0)
        adjusted_value = math.floor(value / step) * step
        adjusted_value = round(adjusted_value, decimal_places)
        if as_string:
            return f"{adjusted_value:.{decimal_places}f}"
        else:
            return adjusted_value

    def printWallet(self):
        for stock in self.account_data["balances"]:
            if float(stock["free"]) > 0:
                print(stock)

    def printStock(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                print(stock)

    def printBrl(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == "BRL":
                print(stock)

    def printOpenOrders(self):
        if self.open_orders:
            print("-------------------------")
            print(f"Ordens abertas para {self.operation_code}:")
            for order in self.open_orders:
                to_print = (
                    f"----"
                    f"\nID {order['orderId']}:"
                    f"\n - Status: {getOrderStatus(order['status'])}"
                    f"\n - Side: {order['side']}"
                    f"\n - Ativo: {order['symbol']}"
                    f"\n - Preço: {order['price']}"
                    f"\n - Quantidade Original: {order['origQty']}"
                    f"\n - Quantidade Executada: {order['executedQty']}"
                    f"\n - Tipo: {order['type']}"
                )
                print(to_print)
            print("-------------------------")
        else:
            print(f"Não há ordens abertas para {self.operation_code}.")

    def getWallet(self):
        for stock in self.account_data["balances"]:
            if float(stock["free"]) > 0:
                return stock

    def getStock(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                return stock

    def getPriceChangePercentage(self, initial_price, close_price):
        if initial_price == 0:
            raise ValueError("O initial_price não pode ser zero.")
        percentual_change = ((close_price - initial_price) / initial_price) * 100
        return percentual_change

    def buyMarketOrder(self, quantity=None):
        try:
            if not self.actual_trade_position:
                if quantity == None:
                    quantity = self.adjust_to_step(self.last_stock_account_balance, self.step_size, as_string=True)
                else:
                    quantity = self.adjust_to_step(quantity, self.step_size, as_string=True)

                order_buy = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity,
                )
                createLogOrder(order_buy)
                print(f"\nOrdem de COMPRA a mercado enviada com sucesso:")
                print(order_buy)
                return order_buy
            else:
                logging.warning("Erro ao comprar: Posição já comprada.")
                print("\nErro ao comprar: Posição já comprada.")
                return False

        except Exception as e:
            logging.error(f"Erro ao executar ordem de compra a mercado: {e}")
            print(f"\nErro ao executar ordem de compra a mercado: {e}")
            return False

    def buyLimitedOrder(self, price=0):

        close_price = self.stock_data["close_price"].iloc[-1]
        volume = self.stock_data["volume"].iloc[-1]
        avg_volume = self.stock_data["volume"].rolling(window=20).mean().iloc[-1]
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])

        if price == 0:
            if rsi < 30:
                limit_price = close_price - (0.002 * close_price)
            elif volume < avg_volume:
                limit_price = close_price + (0.002 * close_price)
            else:
                limit_price = close_price + (0.005 * close_price)
        else:
            limit_price = price

        symbol = self.operation_code
        min_usdt = getattr(self, "min_trade_usdt", 10)
        quantity = self.get_position_size()

        if quantity <= 0:
            print("🚫 Quantidade inválida")
            return False

        print(f"🔎 Antes prepare_order → price: {limit_price}, qty: {quantity}")

        limit_price, quantity = self.prepare_order(symbol, float(limit_price), float(quantity), side="BUY")

        print(f"🔎 Depois prepare_order → price: {limit_price}, qty: {quantity}")

        if not limit_price or not quantity:
            print("🚫 Ordem inválida após prepare_order")
            return False

        limit_price = f"{limit_price:.8f}"
        quantity = f"{quantity:.8f}"

        print(f"\nEnviando ordem limitada de COMPRA para {self.operation_code}:")
        print(f" - RSI: {rsi}")
        print(f" - Quantidade: {quantity}")
        print(f" - Close Price: {close_price}")
        print(f" - Preço Limite: {limit_price}")

        try:
            order_buy = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_BUY,
                type=ORDER_TYPE_LIMIT,
                timeInForce="GTC",
                quantity=quantity,
                price=limit_price,
            )
            print("\n✅ Ordem COMPRA limitada enviada com sucesso")
            if order_buy:
                createLogOrder(order_buy)
            return order_buy

        except Exception as e:
            logging.error(f"Erro ao enviar ordem limitada de COMPRA: {e}")
            print(f"\n❌ Erro ao enviar ordem limitada de COMPRA: {e}")
            return False
        
    def manage_open_position(self, market, decision):
        # =====================================
        # 🚀 SELL ENGINE PROFISSIONAL
        # =====================================
        if self.actual_trade_position:

            current_price = self.stock_data["close_price"].iloc[-1]
            avg_price = self.last_buy_price
            qty = self.last_stock_account_balance

            if avg_price <= 0 or qty <= 0:
                return

            pnl = ((current_price - avg_price) / avg_price) * 100

            rsi = Indicators.getRSI(series=self.stock_data["close_price"])

            position_value = qty * current_price

            print(f"[{self.operation_code}] 💰 PnL: {pnl:.2f}% | RSI: {rsi:.2f}")

            # ===============================
            # 🎯 TARGETS DINÂMICOS
            # ===============================
            if position_value < 10:
                tp1 = 1.0
                tp2 = 1.8
            elif position_value < 30:
                tp1 = 1.5
                tp2 = 2.5
            else:
                tp1 = 2.0
                tp2 = 3.5

            # ===============================
            # 🟢 PARCIAL
            # ===============================
            if not self.partial_done and pnl >= tp1 and qty > self.step_size * 2:

                print(f"[{self.operation_code}] 🟢 Parcial 50%")

                self.sellPartial(0.50)

                self.partial_done = True
                return

            # ===============================
            # 🚀 TAKE PROFIT TOTAL
            # ===============================
            if pnl >= tp2:

                print(f"[{self.operation_code}] 🚀 TP total")

                self.safe_sell_market()
                return

            # ===============================
            # 🛡 BREAK EVEN
            # ===============================
            if self.partial_done and 0.30 <= pnl <= 0.70:

                print(f"[{self.operation_code}] 🛡 Break-even")

                self.sellLimitedOrder()
                return

            # ===============================
            # 🚪 POSIÇÃO TRAVADA EM RANGE
            # ===============================
            if market == "RANGE":

                if -0.4 <= pnl <= 0.3:
                    self.stuck_counter += 1
                else:
                    self.stuck_counter = 0

                if self.stuck_counter >= 8:
                    print(f"[{self.operation_code}] 🚪 Saída posição travada")

                    self.sellLimitedOrder()
                    self.stuck_counter = 0
                    return

            # ===============================
            # 📉 RSI PERDEU FORÇA
            # ===============================
            if pnl > 0.2 and rsi > 68:

                print(f"[{self.operation_code}] 📉 RSI esticado")

                self.sellLimitedOrder()
                return

            # ===============================
            # 🛑 STOP LOSS
            # ===============================
            if pnl <= -3.5:

                print(f"[{self.operation_code}] 🛑 Stop Loss")

                self.safe_sell_market()
                return
            
            if decision == False and pnl > 0:
                print("🔻 Sinal de venda")
                self.sellLimitedOrder()
                return
     
    def sellPartial(self, pct):
        qty = self.last_stock_account_balance * pct
        return self.safe_sell_market(qty)   
    
    def acquire_sell_lock(self):
        with lock:
            if bot_control.get("selling_now", False):
                return False

            bot_control["selling_now"] = True
            return True

    def release_sell_lock(self):
        with lock:
            bot_control["selling_now"] = False


    def safe_sell_market(self, quantity=None):

        if not self.acquire_sell_lock():
            print("⏳ Venda já em andamento...")
            return False

        try:
            return self.sellMarketOrder(quantity)

        finally:
            self.release_sell_lock()

    def sellMarketOrder(self, quantity=None):
        try:
            if quantity is None:
                quantity = self.last_stock_account_balance

            quantity = self.adjust_to_step(quantity, self.step_size, as_string=True)

            return self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )

        except Exception as e:
            print(e)
            return False
    
    def sellLimitedOrder(self, price=None):
        close_price = self.stock_data["close_price"].iloc[-1]
        volume = self.stock_data["volume"].iloc[-1]
        avg_volume = self.stock_data["volume"].rolling(window=20).mean().iloc[-1]
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])

        if price is None:
            if rsi > 70:
                limit_price = close_price + (0.002 * close_price)
            elif volume < avg_volume:
                limit_price = close_price - (0.002 * close_price)
            else:
                limit_price = close_price - (0.005 * close_price)

            if limit_price < (self.last_buy_price * (1 - self.acceptable_loss_percentage)):
                print(f"\nAjuste de venda aceitável ({self.acceptable_loss_percentage*100}%):")
                print(f" - De: {limit_price:.4f}")
                limit_price = self.getMinimumPriceToSell()
                print(f" - Para: {limit_price}")
        else:
            limit_price = price

        symbol = self.operation_code

        limit_price, quantity = self.prepare_order(
            symbol, float(limit_price), float(self.last_stock_account_balance), side="SELL"
        )

        if not limit_price or not quantity:
            print("🚫 Ordem inválida após prepare_order")
            return False

        limit_price = f"{limit_price:.8f}"
        quantity = f"{quantity:.8f}"

        print(f"\nEnviando ordem limitada de VENDA para {self.operation_code}:")
        print(f" - RSI: {rsi}")
        print(f" - Quantidade: {quantity}")
        print(f" - Close Price: {close_price}")
        print(f" - Preço Limite: {limit_price}")

        try:
            order_sell = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_SELL,
                type=ORDER_TYPE_LIMIT,
                timeInForce="GTC",
                quantity=quantity,
                price=limit_price,
            )
            print(f"\nOrdem VENDA limitada enviada com sucesso:")
            createLogOrder(order_sell)
            return order_sell
        except Exception as e:
            logging.error(f"Erro ao enviar ordem limitada de VENDA: {e}")
            print(f"\nErro ao enviar ordem limitada de VENDA: {e}")
            return False

    def getOpenOrders(self):
        return self.client_binance.get_open_orders(symbol=self.operation_code)

    def cancelOrderById(self, order_id):
        self.client_binance.cancel_order(symbol=self.operation_code, orderId=order_id)

    def cancelAllOrders(self):
        if self.open_orders:
            for order in self.open_orders:
                try:
                    self.client_binance.cancel_order(symbol=self.operation_code, orderId=order["orderId"])
                    print(f"❌ Ordem {order['orderId']} cancelada.")
                except Exception as e:
                    print(f"Erro ao cancelar ordem {order['orderId']}: {e}")

    def hasOpenBuyOrder(self):
        self.partial_quantity_discount = 0.0
        try:
            open_orders = self.client_binance.get_open_orders(symbol=self.operation_code)
            buy_orders = [order for order in open_orders if order["side"] == "BUY"]

            if buy_orders:
                self.last_buy_price = 0.0
                print(f"\nOrdens de compra abertas para {self.operation_code}:")
                for order in buy_orders:
                    executed_qty = float(order["executedQty"])
                    price = float(order["price"])
                    print(f" - ID: {order['orderId']}, Preço: {price}, Executada: {executed_qty}")
                    self.partial_quantity_discount += executed_qty
                    if executed_qty > 0 and price > self.last_buy_price:
                        self.last_buy_price = price
                return True
            else:
                print(f" - Não há ordens de compra abertas para {self.operation_code}.")
                return False

        except Exception as e:
            print(f"Erro ao verificar ordens abertas: {e}")
            return False

    def hasOpenSellOrder(self):
        self.partial_quantity_discount = 0.0
        try:
            open_orders = self.client_binance.get_open_orders(symbol=self.operation_code)
            sell_orders = [order for order in open_orders if order["side"] == "SELL"]

            if sell_orders:
                print(f"\nOrdens de venda abertas para {self.operation_code}:")
                for order in sell_orders:
                    executed_qty = float(order["executedQty"])
                    print(f" - ID: {order['orderId']}, Preço: {order['price']}, Executada: {executed_qty}")
                    self.partial_quantity_discount += executed_qty
                return True
            else:
                print(f" - Não há ordens de venda abertas para {self.operation_code}.")
                return False

        except Exception as e:
            print(f"Erro ao verificar ordens abertas: {e}")
            return False

    def getFinalDecisionStrategy(self):
        final_decision = StrategyRunner.execute(
            self,
            stock_data=self.stock_data,
            main_strategy=self.main_strategy,
            main_strategy_args=self.main_strategy_args,
            fallback_strategy=self.fallback_strategy,
            fallback_strategy_args=self.fallback_strategy_args,
        )
        return final_decision

    def getMinimumPriceToSell(self):
        return self.last_buy_price * (1 - self.acceptable_loss_percentage)

    def stopLossTrigger(self):
        close_price = self.stock_data["close_price"].iloc[-1]
        stop_loss_price = self.last_buy_price * (1 - self.stop_loss_percentage)

        print(f'\n - Preço atual: {self.stock_data["close_price"].iloc[-1]}')
        print(f" - Preço mínimo para vender: {self.getMinimumPriceToSell()}")
        print(f" - Stop Loss em: {stop_loss_price:.4f} (-{self.stop_loss_percentage*100:.2f}%)\n")

        if self.isBought() and (close_price < stop_loss_price or (self.detect_dump() and not self.is_oversold())):
            print("🔴 Ativando STOP LOSS...")
            self.cancelAllOrders()
            time.sleep(2)
            self.safe_sell_market()
            return True   

    def takeProfitTrigger(self):
        """
        Verifica se o preço atingiu uma meta de take profit e realiza venda parcial.
        ✅ BUG 3 — stop_loss_percentage ajustado apenas para trailing; restaurado pelo _reset_position_state() ao vender.
        """
        try:
            close_price = self.stock_data["close_price"].iloc[-1]
            price_percentage_variation = self.getPriceChangePercentage(
                initial_price=self.last_buy_price, close_price=close_price
            )

            print(f" - Variação atual: {price_percentage_variation:.2f}%")

            if self.take_profit_index < len(self.take_profit_at_percentage):
                tp_percentage = self.take_profit_at_percentage[self.take_profit_index]
                tp_amount = self.take_profit_amount_percentage[self.take_profit_index]

                print(f" - Próxima meta Take Profit: {tp_percentage}% (Venda de: {tp_amount}%)\n")

                if (
                    self.actual_trade_position
                    and tp_percentage > 0
                    and round(price_percentage_variation, 2) >= round(tp_percentage, 2)
                ):
                    if self.take_profit_index >= len(self.take_profit_at_percentage):
                        return False

                    if self.initial_balance_position == 0:
                        print("⚠️ Posição inicial não definida")
                        return False

                    quantity_to_sell = self.initial_balance_position * (tp_amount / 100)
                    quantity_to_sell = self.adjust_to_step(quantity_to_sell, self.step_size, as_string=False)
                    quantity_to_sell = min(quantity_to_sell, self.last_stock_account_balance)

                    if quantity_to_sell > 0:
                        log = (
                            f"🎯 Meta de Take Profit atingida! ({tp_percentage}% lucro)\n"
                            f" - Vendendo {tp_amount}% da carteira...\n"
                            f" - Preço atual: {close_price:.4f}\n"
                            f" - Quantidade vendida: {quantity_to_sell:.6f} {self.stock_code}"
                        )
                        print(log)
                        logging.info(log)

                        order_result = self.sellMarketOrder(quantity=quantity_to_sell)
                        send_telegram(f"🎯 TAKE PROFIT {self.operation_code}\nLucro: {price_percentage_variation:.2f}%")

                        if order_result and "status" in order_result and order_result["status"] == "FILLED":
                            self.take_profit_index += 1

                            # ✅ BUG 3 — Trailing stop: aperta o stop apenas se o ganho justifica
                            # O valor original é restaurado pelo _reset_position_state() quando vender de vez
                            gain = self.getPriceChangePercentage(self.last_buy_price, close_price)
                            if gain > 4:
                                new_sl = 0.005
                            elif gain > 2:
                                new_sl = 0.002
                            else:
                                new_sl = self.initial_stop_loss_percentage

                            # Só aperta se for menor que o stop atual (nunca alarga)
                            if new_sl < self.stop_loss_percentage:
                                print(f"🔒 Trailing stop: {self.stop_loss_percentage:.4f} → {new_sl:.4f}")
                                self.stop_loss_percentage = new_sl

                            print(f"✅ Take Profit {tp_percentage}% realizado com sucesso!")
                            return True
                        else:
                            print(f"❌ Falha ao executar a ordem de venda.")
                            return False
                    else:
                        print("⚠️ Quantidade de venda inválida.")
                        return False
            else:
                print("ℹ️ Todas as metas de take profit já foram atingidas.")
                return False

        except Exception as e:
            logging.error(f"Erro no take profit: {e}")
            print(f"❌ Erro no take profit: {e}")
            return False

    def update_trailing_stop(self):
        if not self.isBought():
            return

        current_price = self.stock_data["close_price"].iloc[-1]
        gain = self.getPriceChangePercentage(self.last_buy_price, current_price)

        if gain > 5:
            self.stop_loss_percentage = min(self.stop_loss_percentage, 0.03)
        elif gain > 3:
            self.stop_loss_percentage = min(self.stop_loss_percentage, 0.02)
        elif gain > 1:
            self.stop_loss_percentage = min(self.stop_loss_percentage, 0.01)

    def create_order(self, _symbol, _side, _type, _quantity, _timeInForce=None, _limit_price=None, _stop_price=None):
        order_buy = TraderOrder.create_order(
            self.client_binance,
            _symbol=_symbol,
            _side=_side,
            _type=_type,
            _timeInForce=_timeInForce,
            _quantity=_quantity,
            _limit_price=_limit_price,
            _stop_price=_stop_price,
        )
        return order_buy

    def execute(self):

        self.updateAllData()

        score = 0
        min_score = 0
        market = self.detect_market_condition()

        from src.state import best_asset

        with lock:
            if "last_reset" not in best_asset:
                best_asset["last_reset"] = time.time()

            if time.time() - best_asset["last_reset"] > 60:
                best_asset["score"] = 0
                best_asset["symbol"] = None
                best_asset["last_reset"] = time.time()
                print("🔄 Resetando melhor ativo")

        with lock:
            running = bot_control["running"]

        if not running:
            print("⏸ Bot pausado via painel")
            return

        if not self.can_trade():
            return

        if not hasattr(self, "stock_data") or self.stock_data is None or len(self.stock_data) == 0:
            print("⚠️ Dados ainda não carregados")
            return

        print("------------------------------------------------")
        print(f'🟢 Executado {datetime.now().strftime("(%H:%M:%S) %d-%m-%Y")}\n')

        if not self.isBought():
            score = self.calculate_entry_score()

            if market == "TREND":
                min_score = 2
            elif market == "RANGE":
                min_score = 1
            else:
                min_score = 2

            print(f"📊 Min Score necessário: {min_score}")

            with lock:
                if score > best_asset.get("score", 0):
                    best_asset["score"] = score
                    best_asset["symbol"] = self.operation_code
                    print(f"🏆 Melhor ativo atualizado: {self.operation_code} | Score: {score}")

            if score < min_score:
                print(f"🚫 Score insuficiente ({score})")
                return

        last = self.stock_data.iloc[-1]

        candle = {
            "x": datetime.now().timestamp() * 1000,
            "o": float(last["open_price"]),
            "h": float(last["high_price"]),
            "l": float(last["low_price"]),
            "c": float(last["close_price"]),
        }

        bot_status.setdefault("candles", []).append(candle)
        bot_status["candles"] = bot_status["candles"][-100:]

        self.update_trailing_stop()

        bot_status["balance"] = self.getUSDTBalance()
        bot_status["positions"][self.operation_code] = {
            "position": "LONG" if self.actual_trade_position else "OUT",
            "price": float(last["close_price"])
        }

        score_label = score if not self.isBought() else "LOCKED"
        print(f"🧠 Estratégia Híbrida | Mercado: {market} | Score: {score_label}")

        if market == "TREND":
            decision = getVortexTradeStrategy(self.stock_data, verbose=True)

        elif market == "RANGE":
            decision = getRsiTradeStrategy(self.stock_data, low=30, high=70, verbose=True)

        else:
            vortex = getVortexTradeStrategy(self.stock_data, verbose=True)
            rsi = getRsiTradeStrategy(self.stock_data, low=35, high=65, verbose=True)

            if vortex == True or rsi == True:
                decision = True
            elif vortex == False and rsi == False:
                decision = False
            else:
                decision = None

        if decision is None:
            print("⚠️ Estratégia inconclusiva")
            return

        self.last_trade_decision = decision

        print("\n--------------")
        print(f'🔎 Decisão Final: {"Comprar" if decision else "Vender"}')

        if not self.isBought() and score <= 0:
            print("🚫 Score zerado")
            return

        # ================================
        # 🟢 COMPRA
        # ================================
        if not self.isBought() and decision == True:

            with lock:
                if best_asset.get("symbol") != self.operation_code:
                    print(f"🚫 {self.operation_code} ignorado (não é o melhor)")
                    return

                if bot_control.get("buying_now", False) or bot_control.get("selling_now", False):
                    print(f"⏳ Compra em andamento por outro ativo...")
                    return

                bot_control["buying_now"] = True

            try:
                print("🏁 COMPRANDO...")
                order = self.buyLimitedOrder()

                if not order:
                    print("❌ Falha na compra")
                    return

                time.sleep(2)
                self.updateAllData()

                if self.isBought():
                    self.initial_balance_position = self.last_stock_account_balance
                    print("✅ Compra confirmada")

            finally:
                with lock:
                    bot_control["buying_now"] = False
                    
        if self.isBought():
            self.manage_open_position(market, decision)
            return

        # ================================
        # 🔴 VENDA POR SINAL
        # ================================
        if self.isBought() and decision == False:

            with lock:
                if bot_control.get("selling_now", False):
                    print("⏳ Venda em andamento por outro ativo...")
                    return
                bot_control["selling_now"] = True

            try:
                print("🏁 VENDENDO...")
                order = self.sellLimitedOrder()

                if not order:
                    print("❌ Falha na venda")
                    return

                time.sleep(2)
                self.updateAllData()

                if not self.isBought():
                    # ✅ BUG 2 + BUG 3 — updateAllData → getActualTradePosition → _reset_position_state()
                    # O reset já acontece automaticamente dentro de getActualTradePosition()
                    print("📉 Venda confirmada | take_profit_index e stop_loss resetados ✅")

            finally:
                with lock:
                    bot_control["selling_now"] = False

        print("------------------------------------------------")

    def load_exchange_info(self):
        if not hasattr(self, "_exchange_cache"):
            print("📡 Carregando filtros da Binance...")
            info = self.client_binance.get_exchange_info()
            self._exchange_cache = {
                s['symbol']: {f['filterType']: f for f in s['filters']}
                for s in info['symbols']
            }

    def get_symbol_filters(self, symbol):
        self.load_exchange_info()
        if symbol not in self._exchange_cache:
            raise Exception(f"❌ Símbolo não encontrado: {symbol}")
        return self._exchange_cache[symbol]

    def get_min_notional(self, symbol):
        filters = self.get_symbol_filters(symbol)
        if 'MIN_NOTIONAL' in filters:
            return float(filters['MIN_NOTIONAL']['minNotional'])
        elif 'NOTIONAL' in filters:
            return float(filters['NOTIONAL']['minNotional'])
        else:
            print(f"⚠️ MIN_NOTIONAL não encontrado para {symbol}")
            return 5.0

    def prepare_order(self, symbol, price, quantity, side="BUY"):
        try:
            print("\n🧠 Preparando ordem inteligente...")
            filters = self.get_symbol_filters(symbol)

            tick_size = float(filters['PRICE_FILTER']['tickSize'])
            step_size = float(filters['LOT_SIZE']['stepSize'])
            min_qty = float(filters['LOT_SIZE']['minQty'])

            if 'MIN_NOTIONAL' in filters:
                min_notional = float(filters['MIN_NOTIONAL']['minNotional'])
            elif 'NOTIONAL' in filters:
                min_notional = float(filters['NOTIONAL']['minNotional'])
            else:
                min_notional = 5.20

            price = math.floor(price / tick_size) * tick_size
            price = float(f"{price:.8f}")

            quantity = math.ceil(quantity / step_size) * step_size

            if quantity < min_qty:
                quantity = min_qty

            notional = price * quantity

            if notional < min_notional:
                print(f"⚠️ NOTIONAL baixo: {notional:.2f} < {min_notional}")
                quantity = min_notional / price
                quantity = math.ceil(quantity / step_size) * step_size
                print(f"🔧 Nova quantidade ajustada: {quantity}")

            notional = price * quantity

            if notional < min_notional:
                print(f"🚫 Ordem abortada: NOTIONAL final ainda inválido ({notional:.2f})")
                return None, None

            print(f"""
📊 ORDEM AJUSTADA:
- Side: {side}
- Preço: {price}
- Quantidade: {quantity}
- Notional: {notional:.2f} USDT
- Min Notional: {min_notional}
            """)

            return float(f"{price:.8f}"), float(f"{quantity:.8f}")

        except Exception as e:
            print(f"❌ Erro no prepare_order: {e}")
            return None, None

    def detect_dump(self, threshold=-0.025, candles=3):
        try:
            prices = self.stock_data["close_price"]
            if len(prices) < candles + 1:
                return False
            recent = prices.iloc[-candles:]
            drop = (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0]
            print(f"📉 Variação últimos {candles} candles: {drop*100:.2f}%")
            if drop <= threshold:
                print("🚫 DUMP DETECTADO")
                return True
            return False
        except Exception as e:
            print(f"Erro detect_dump: {e}")
            return False

    def is_oversold(self, rsi_limit=30):
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])
        print(f"📊 RSI atual: {rsi:.2f}")
        return rsi < rsi_limit

    def is_price_stretched(self, symbol, price, threshold=None):
        try:
            ma50 = self.stock_data["close_price"].rolling(window=50).mean().iloc[-1]
            if ma50 == 0:
                return False
            vol = self.stock_data["close_price"].pct_change().rolling(20).std().iloc[-1]
            if threshold is None:
                threshold = min(max(0.02, vol * 3), 0.08)
            distance = (price - ma50) / ma50
            print(f"📏 Distância da MA50: {distance*100:.2f}% | Threshold: {threshold*100:.2f}%")
            return distance > threshold
        except Exception as e:
            print(f"Erro is_price_stretched: {e}")
            return False

    def detect_pump(self, candles=3, threshold=None):
        try:
            prices = self.stock_data["close_price"]
            if len(prices) < candles + 1:
                return False
            start = prices.iloc[-candles - 1]
            end = prices.iloc[-1]
            change = (end - start) / start
            vol = self.stock_data["close_price"].pct_change().rolling(20).std().iloc[-1]
            if threshold is None:
                threshold = min(max(0.02, vol * 2), 0.08)
            print(f"🚀 Pump check: {change*100:.2f}% | Threshold: {threshold*100:.2f}%")
            return change >= threshold
        except Exception as e:
            print(f"Erro detect_pump: {e}")
            return False

    def is_overbought(self, limit=70):
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])
        print(f"📊 RSI atual: {rsi:.2f}")
        return rsi > limit

    def calculate_entry_score(self):
        try:
            score = 0
            close = self.stock_data["close_price"]
            volume = self.stock_data["volume"]
            price = close.iloc[-1]
            prev_price = close.iloc[-2]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma50 = close.rolling(50).mean().iloc[-1]
            ma200 = close.rolling(200).mean().iloc[-1]
            avg_vol = volume.rolling(20).mean().iloc[-1]
            current_vol = volume.iloc[-1]
            rsi = Indicators.getRSI(series=close)
            market = self.detect_market_condition()

            print(f"🧠 Market Mode: {market}")

            if market == "TREND":
                if price > ma50: score += 2
                if ma50 > ma200: score += 2
                if price > prev_price: score += 1
                if rsi < 68: score += 1
                if current_vol > avg_vol: score += 1

            elif market == "RANGE":
                if rsi < 45: score += 2
                if rsi < 38: score += 1
                if price < ma20: score += 1
                if price < ma50: score += 1
                if current_vol > avg_vol: score += 1

            else:
                if price > ma50: score += 1
                if rsi < 45: score += 1
                if current_vol > avg_vol: score += 1

            recent_move = (price - close.iloc[-4]) / close.iloc[-4]
            if recent_move > 0.03:
                score -= 2
                print("🚫 Pump detectado (-2 score)")

            if rsi > 75:
                score -= 2

            score = max(score, 0)
            print(f"🧠 Entry Score final: {score}")
            return score

        except Exception as e:
            print(f"Erro calculate_entry_score: {e}")
            return 0

    def can_open_new_position(self):
        try:
            count = 0
            for asset in self.account_data["balances"]:
                if float(asset["free"]) > 0 and asset["asset"] != "USDT":
                    count += 1
            print(f"📊 Posições abertas: {count}")
            return count < GLOBAL_MANAGER["max_positions"]
        except Exception as e:
            print(f"Erro exposição: {e}")
            return False

    def get_position_size(self, risk_percent=0.02):
        balance_usdt = self.getUSDTBalance()
        volatility = self.stock_data["close_price"].pct_change().rolling(20).std().iloc[-1]
        if volatility > 0:
            volatility = max(volatility, 0.002)
            risk_adjusted = risk_percent / (volatility * 100)
        else:
            risk_adjusted = risk_percent
        risk_value = balance_usdt * min(risk_adjusted, 0.02)
        price = self.stock_data["close_price"].iloc[-1]
        quantity = risk_value / price
        print(f"💰 Position size: {quantity}")
        min_usdt = 6.0
        quantity = max(quantity, min_usdt / price)
        return quantity

    def is_trend_up(self):
        ma50 = self.stock_data["close_price"].rolling(50).mean().iloc[-1]
        ma200 = self.stock_data["close_price"].rolling(200).mean().iloc[-1]
        return ma50 > ma200

    def can_trade(self):
        if self.daily_loss > 0.05:
            print("🚫 Limite diário atingido")
            return False
        return True

    def getUSDTBalance(self):
        try:
            for asset in self.account_data["balances"]:
                if asset["asset"] == "USDT":
                    return float(asset["free"])
            return 0.0
        except:
            return 0.0

    def get_market_score(self):
        score = 0
        market = self.detect_market_condition()
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])
        price = self.stock_data["close_price"].iloc[-1]
        ma50 = self.stock_data["close_price"].rolling(50).mean().iloc[-1]
        if market == "TREND":
            score += 2
            if price > ma50: score += 2
        elif market == "RANGE":
            if rsi < 40: score += 2
        else:
            if rsi < 50: score += 1
        return score

    def get_real_open_positions(self, min_usdt=10):
        count = 0
        try:
            for asset in self.account_data["balances"]:
                asset_name = asset["asset"]
                free = float(asset["free"])
                if asset_name == "USDT":
                    continue
                if free <= 0:
                    continue
                try:
                    symbol = asset_name + "USDT"
                    ticker = self.client_binance.get_symbol_ticker(symbol=symbol)
                    price = float(ticker["price"])
                except:
                    continue
                value = free * price
                if value >= min_usdt:
                    count += 1
            return count
        except Exception as e:
            print(f"Erro ao contar posições reais: {e}")
            return 0

    def detect_market_condition(self):
        try:
            rsi = Indicators.getRSI(series=self.stock_data["close_price"])
            ma50 = self.stock_data["close_price"].rolling(50).mean().iloc[-1]
            ma200 = self.stock_data["close_price"].rolling(200).mean().iloc[-1]
            vol = self.stock_data["close_price"].pct_change().rolling(20).std().iloc[-1]

            print(f"📊 Market Check → RSI: {rsi:.2f} | Vol: {vol:.4f}")

            if ma50 > ma200 and vol > 0.006:
                return "TREND"
            if vol < 0.0045:
                return "RANGE"
            return "NEUTRAL"

        except Exception as e:
            print(f"Erro detect_market_condition: {e}")
            return "NEUTRAL"