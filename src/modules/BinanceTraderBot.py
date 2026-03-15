# fmt: off
import os
import json
import time
import logging
import math
import threading
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd
from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, ORDER_TYPE_STOP_LOSS_LIMIT
from binance.exceptions import BinanceAPIException

from src.modules.BinanceClient import BinanceClient
from src.modules.TraderOrder import TraderOrder
from src.modules.Logger import *
from src.modules.StrategyRunner import StrategyRunner

from src.strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from src.strategies.moving_average import getMovingAverageTradeStrategy

from src.utils.trade_logger import log_trade

from src.indicators import Indicators

from src import main


# fmt: on

load_dotenv()
api_key = os.getenv("BINANCE_API_KEY")
secret_key = os.getenv("BINANCE_SECRET_KEY")

STATE_FILE = "bot_state.json"

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
        api_key,
        api_secret,
        config=None,
        testnet=False,
        time_to_trade=30 * 60,
        delay_after_order=60 * 60,
        acceptable_loss_percentage=0.5,
        stop_loss_percentage=3.5,
        fallback_activated=True,
        
        take_profit_at_percentage=None,
        take_profit_amount_percentage=None,
        
        main_strategy=None,
        main_strategy_args=None,
        fallback_strategy=None,
        fallback_strategy_args=None,
    ):

        print("------------------------------------------------")
        print("🤖 Robo Trader iniciando...")
        
        # 🔐 Credenciais da Binance
        self.config = config
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        self.capital = 15 #traded_quantity  # valor em USDT configurado por ativo
        
        self.trailing_activation = config["TRAILING"]["ACTIVATION"] / 100
        self.trailing_stop_percent = config["TRAILING"]["DISTANCE"] / 100
        self.trailing_stop_price = 0.0
        self.highest_price_since_entry = 0.0
        
        # Controle de posição atual
        self.actual_trade_position = None
        self.entry_price = 0.0
        self.position_quantity = 0.0
        
        self.sideways_counter = 0
        self.sideways_limit = 3  # nº de ciclos tolerados em lateralização
        
        self.daily_profit = 0.0
        self.daily_trades = 0
        self.last_closed_order_id = None
        self.current_day = datetime.now().date()
        
        self.trades_cache = None
        self.trades_cache_time = 0
        
        # limite de trades por dia
        self.max_daily_trades = config["RISK"]["MAX_TRADES_PER_DAY"]
        
        # 🎯 Modo híbrido de realização parcial
        self.partial_take_profit_levels = [0.8, 1.6, 3.0]  # %
        self.partial_take_profit_amounts = [30, 30, 30]   # % da posição
        self.partial_tp_index = 0
        
        # fmt: off

        self.stock_code = stock_code  # Código princial da stock negociada (ex: 'BTC')
        self.operation_code = operation_code  # Código negociado/moeda (ex:'BTCBRL')
        self.traded_quantity = traded_quantity  # Quantidade incial que será operada
        self.traded_percentage = traded_percentage  # Porcentagem do total da carteira, que será negociada        
        self.candle_period = str(candle_period).strip().lower()  # Período levado em consideração para operação (ex: 15min)        

        self.min_volatility = self.config["SCANNER"]["MIN_VOLATILITY"]
        self.max_volatility = self.config["SCANNER"]["MAX_VOLATILITY"]

        self.last_dust_check = 0
        
        self.scaling_done = False
        self.scale_trigger_profit = 0.6   # %
        self.scale_size_multiplier = 0.5  # adiciona 50% da posição inicial
        
        self.scale_level = 0
        self.max_scale_levels = 3
        
        self.scale_trigger_levels = [0.5, 1.0, 1.8]  # % lucro
        
        self.scanner_cache = []
        self.scanner_cache_time = 0
        self.scanner_cache_ttl = 5  # segundos
        
        self.scanner_ranking = []
        self.last_scan_time = 0
        self.scan_interval = 30  # segundos entre scans
        
        self.operation_code = None
        
        self.symbol_cooldown = {}
        self.symbol_cooldown_time = 30

        VALID_INTERVALS = [
            "1m","3m","5m","15m","30m",
            "1h","2h","4h","6h","8h","12h",
            "1d","3d","1w"
        ]

        if self.candle_period not in VALID_INTERVALS:
            raise ValueError(f"Intervalo inválido enviado ao bot: {self.candle_period}")

        self.fallback_activated = fallback_activated  # Define se a estratégia de Fallback será usada (ela pode entrar comprada em mercados subindo)
        self.acceptable_loss_percentage = acceptable_loss_percentage / 100 # % Máxima que o bot aceita perder quando vender
        self.stop_loss_percentage = stop_loss_percentage / 100 # % Máxima de loss que ele aceita, em caso de não vender na ordem limitada

        self.take_profit_at_percentage = take_profit_at_percentage or [] # Quanto de valorização para pegar lucro. (Array exemplo: [2, 5, 10])
        self.take_profit_amount_percentage = take_profit_amount_percentage or [] # Quanto da quantidade tira de lucro. (Array exemplo: [25, 25, 40])

        self.main_strategy = main_strategy # Estratégia principal
        self.main_strategy_args = main_strategy_args # (opcional) Argumentos da estratégia principal
        self.fallback_strategy = fallback_strategy # (opcional) Estratégia de Fallback
        self.fallback_strategy_args = fallback_strategy_args # (opcional) Argumentos da estratégia de fallback

        # Configurações de tempos de espera
        self.time_to_trade = time_to_trade
        self.delay_after_order = delay_after_order
        self.time_to_sleep = time_to_trade
        
        self.last_trend_check = 0
        self.cached_trend = False
        
        self.break_even_activated = False
        
        self.last_orderbook_check = 0
        self.cached_orderbook = None
        
        self.lock = threading.Lock()
        
        self.last_trade_time = 0
        self.trade_cooldown = 30  # segundos

        self.max_daily_loss = 10
        
        self.hourly_trades = 0
        self.last_hour = datetime.now().hour
        self.max_hourly_trades = 6
        
        self.last_account_update = 0
        self.cached_account = None
        
        self.orders_cache = None
        self.orders_cache_time = 0

        self.daily_orders_cache = None
        self.daily_orders_time = 0
        
        self.market_cache = None
        self.market_cache_time = 0
        
        self.candles_cache = {}
        self.candles_cache_time = {}
        self.candle_cache_ttl = 15

        for attempt in range(5):
            try:
                self.client_binance = BinanceClient(
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    testnet=self.testnet
                )

                # teste simples de conexão
                self.client_binance.get_server_time()

                print("✅ Conectado à Binance")
                break

            except Exception as e:
                print(f"⚠️ Falha ao conectar Binance (tentativa {attempt+1}/5)")
                time.sleep(3)

        else:
            raise Exception("❌ Não foi possível conectar à Binance")
                
        threading.Thread(target=self.dust_manager, daemon=True).start()
                
        # Break-even configurável por ativo
        self.break_even_map = {
            "BTC": 1.2 / 100,
            "SOL": 1.0 / 100,
            "BNB": 1.0 / 100,
            "ADA": 0.8 / 100,
            "XRP": 0.8 / 100,
            "SHIB": 0.6 / 100,
        }
        
        default_be = config["BREAK_EVEN"]["ACTIVATION"] / 100
        self.break_even_activation = self.break_even_map.get(self.stock_code, default_be)

        # fallback padrão
        #self.break_even_activation = self.break_even_map.get(self.stock_code, 1.0 / 100)
                

        self.setStepSizeAndTickSize() # Seta o time_step e step_size da classe (só precisa executar 1x)

        self.loadBotState()
        
        # fmt: on
        
        
    def trailingStopTrigger(self):
        if not self.actual_trade_position or self.last_buy_price <= 0:
            return False

        if self.last_stock_account_balance <= 0:
            return False

        if self.stock_data is None or self.stock_data.empty:
            return False

        close_price = self.stock_data["close_price"].iloc[-1]

        # Atualiza o maior preço desde a entrada
        if self.highest_price_since_entry == 0 or close_price > self.highest_price_since_entry:
            self.highest_price_since_entry = close_price
            
        # Ativa trailing só depois de lucro mínimo (0.5%)
        activation_price = self.last_buy_price * (1 + self.trailing_activation)

        if self.highest_price_since_entry < activation_price:
            return False

        # Trailing baseado no topo (não no preço atual)
        new_trailing = self.highest_price_since_entry * (1 - self.trailing_stop_percent)

        # Só sobe, nunca desce
        if new_trailing > self.trailing_stop_price:
            self.trailing_stop_price = new_trailing
            print(f"📈 Trailing Stop atualizado: {self.trailing_stop_price:.4f}")

        # Se perder o trailing → vende
        if self.trailing_stop_price > 0 and close_price <= self.trailing_stop_price:
            print("🔴 Trailing Stop acionado! Vendendo posição...")
            self.cancelAllOrders()
            time.sleep(1)
            self.sellMarketOrder()
            return True

        return False
    
    def getTrendMultiTimeframe(self):
        """
        Retorna True se tendência estiver alinhada em:
        5m + 15m + 1h (usando médias móveis)

        Usa cache de 5 minutos para evitar excesso de chamadas na API.
        """

        try:

            # 🔒 Usa cache se já verificou recentemente
            if time.time() - self.last_trend_check < 300:
                return self.cached_trend

            def get_ma_trend(interval):

                candles = self.getCachedKlines(
                    symbol=self.operation_code,
                    interval=interval,
                    limit=100
                )

                if not candles:
                    return False

                df = pd.DataFrame(candles)

                df.columns = [
                    "open_time","open","high","low","close","volume",
                    "close_time","qav","trades","tbav","tqav","ignore"
                ]

                df["close"] = pd.to_numeric(df["close"])

                ma_fast = df["close"].rolling(5).mean().iloc[-1]
                ma_slow = df["close"].rolling(20).mean().iloc[-1]

                return ma_fast > ma_slow

            trend_5m = get_ma_trend(Client.KLINE_INTERVAL_5MINUTE)
            trend_15m = get_ma_trend(Client.KLINE_INTERVAL_15MINUTE)
            trend_1h = get_ma_trend(Client.KLINE_INTERVAL_1HOUR)

            print("\n📊 Tendência Multi-Timeframe:")
            print(f" - 5m  : {'ALTA' if trend_5m else 'BAIXA'}")
            print(f" - 15m : {'ALTA' if trend_15m else 'BAIXA'}")
            print(f" - 1h  : {'ALTA' if trend_1h else 'BAIXA'}")

            bull_count = sum([trend_5m, trend_15m, trend_1h])
            result = bull_count >= 2

            # 💾 salva no cache
            self.cached_trend = result
            self.last_trend_check = time.time()

            return result

        except Exception as e:

            print(f"Erro ao verificar tendência multi-timeframe: {e}")

            return False
        
    # Atualiza todos os dados da conta
    def updateAllData(self, verbose=False):
        try:
            # 1️⃣ Dados atualizados da conta
            self.account_data = self.getUpdatedAccountData()

            if self.account_data is None:
                print("⚠️ Falha ao obter dados da conta.")
                return False

            # 2️⃣ Dados de mercado
            self.stock_data = self.getStockData()
            if self.stock_data is None or self.stock_data.empty:
                print("⚠️ Falha ao obter stock_data. Pulando ciclo.")
                return False

            # 3️⃣ Balanço atual do ativo
            self.last_stock_account_balance = self.getLastStockAccountBalance()

            # 4️⃣ Detecta posição real
            close_price = self.stock_data["close_price"].iloc[-1]
            position_value = self.last_stock_account_balance * close_price

            MIN_POSITION_VALUE = 5  # mínimo em USDT para considerar posição ativa

            self.actual_trade_position = position_value >= MIN_POSITION_VALUE

            # 5️⃣ Ordens abertas
            self.open_orders = self.getOpenOrders()

            # 6️⃣ Últimos preços executados
            self.last_buy_price = self.getLastBuyPrice(verbose)
            self.last_sell_price = self.getLastSellPrice(verbose)
            
            # 7️⃣ Reset do índice de take profit se não estiver posicionado
            if not self.actual_trade_position and self.last_stock_account_balance * close_price < 5:
                self.take_profit_index = 0

            self.reconcilePositionWithWallet()
            
            return True

        except Exception as e:
            print(f"❌ Erro geral ao atualizar dados: {e}")
            return False
         
    # GETS Principais

    # Busca infos atualizada da conta Binance
    def getUpdatedAccountData(self):

        if self.cached_account is not None and time.time() - self.last_account_update < 10:
            return self.cached_account

        data = self.client_binance.get_account()

        self.cached_account = data
        self.last_account_update = time.time()

        return data
    
    # Busca o último balanço da conta, na stock escolhida.
    def getLastStockAccountBalance(self):

        in_wallet_amount = 0.0

        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                free = float(stock["free"])
                locked = float(stock["locked"])
                in_wallet_amount = free + locked

        return float(in_wallet_amount)

    # Checa se a posição atual é comprado ou vendido
    # Checa se a posição atual é comprado ou vendido
    def getActualTradePosition(self):
        """
        Determina a posição atual (comprado ou vendido) com base no saldo da moeda.
        Usa o stepSize da Binance para ajustar o limite mínimo.
        """
        # print(f'STEP SIZE: {self.step_size}')
        try:
            # Verifica se o saldo é maior que o step_size
            if self.last_stock_account_balance >= self.step_size:
                return True  # Comprado
            else:
                return False  # Vendido

        except Exception as e:
            print(f"Erro ao determinar a posição atual para {self.operation_code}: {e}")
            return False  # Retorna como vendido por padrão em caso de erro

    # Busca os dados do ativo no periodo
    def getStockData(
        self,
    ):

        # Busca dados na binance dos últimos 1000 períodos
        candles = self.getCachedKlines(
            symbol=self.operation_code,
            interval=str(self.candle_period).strip(),
            limit=200,
        )

        # Transforma um um DataFrame Pandas
        prices = pd.DataFrame(candles)

        # Renomea as colunas baseada na Documentação da Binance
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

        # Pega apenas os indicadores que queremos para esse modelo
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

        # Converte as colunas para o tipo numérico
        prices["close_price"] = pd.to_numeric(
            prices["close_price"],
            errors="coerce",
        )
        prices["open_price"] = pd.to_numeric(
            prices["open_price"],
            errors="coerce",
        )
        prices["high_price"] = pd.to_numeric(
            prices["high_price"],
            errors="coerce",
        )
        prices["low_price"] = pd.to_numeric(
            prices["low_price"],
            errors="coerce",
        )
        prices["volume"] = pd.to_numeric(
            prices["volume"],
            errors="coerce",
        )

        # Corrige o tempo de fechamento
        prices["open_time"] = pd.to_datetime(
            prices["open_time"],
            unit="ms",
        ).dt.tz_localize("UTC")

        # Converte para o fuso horário UTC -3
        prices["open_time"] = prices["open_time"].dt.tz_convert("America/Sao_Paulo")

        # CÁLCULOS PRÉVIOS...

        return prices

    # Retorna o preço da última ordem de compra executada para o ativo configurado.
    # Retorna 0.0 se nenhuma ordem de compra foi encontrada.
    def getLastBuyPrice(
        self,
        verbose=False,
    ):
        try:
            # Obtém o histórico de ordens do par configurado
            if hasattr(self, "orders_cache") and time.time() - self.orders_cache_time < 10:
                all_orders = self.orders_cache
            else:
                all_orders = self.client_binance.get_all_orders(symbol=self.operation_code, limit=100)
                self.orders_cache = all_orders
                self.orders_cache_time = time.time()

            # Filtra apenas as ordens de compra executadas (FILLED)
            executed_buy_orders = [order for order in all_orders if order["side"] == "BUY" and order["status"] == "FILLED"]

            if executed_buy_orders:
                # Ordena as ordens por tempo (timestamp) para obter a mais recente
                last_executed_order = sorted(
                    executed_buy_orders,
                    key=lambda x: x["time"],
                    reverse=True,
                )[0]

                # print(f'ÚLTIMA EXECUTADA: {last_executed_order}')

                # Retorna o preço da última ordem de compra executada
                last_buy_price = float(last_executed_order["cummulativeQuoteQty"]) / float(last_executed_order["executedQty"])
                # Corrige o timestamp para a chave correta
                datetime_transact = datetime.utcfromtimestamp(last_executed_order["time"] / 1000).strftime("(%H:%M:%S) %d-%m-%Y")
                if verbose:
                    print(f"\nÚltima ordem de COMPRA executada para {self.operation_code}:")
                    print(
                        f" - Data: {datetime_transact} | Preço: {self.adjust_to_step(last_buy_price,self.tick_size, as_string=True)} | Qnt.: {self.adjust_to_step(float(last_executed_order['origQty']), self.step_size, as_string=True)}"
                    )

                return last_buy_price
            else:
                if verbose:
                    print(f"Não há ordens de COMPRA executadas para {self.operation_code}.")
                return 0.0

        except Exception as e:
            if verbose:
                print(f"Erro ao verificar a última ordem de COMPRA executada para {self.operation_code}: {e}")
            return 0.0

    # Retorna o preço da última ordem de venda executada para o ativo configurado.
    # Retorna 0.0 se nenhuma ordem de venda foi encontrada.
    def getLastSellPrice(
        self,
        verbose=False,
    ):
        try:
            # Obtém o histórico de ordens do par configurado
            if hasattr(self, "orders_cache") and time.time() - self.orders_cache_time < 10:
                all_orders = self.orders_cache
            else:
                all_orders = self.client_binance.get_all_orders(symbol=self.operation_code, limit=100)
                self.orders_cache = all_orders
                self.orders_cache_time = time.time()

            # Filtra apenas as ordens de venda executadas (FILLED)
            executed_sell_orders = [order for order in all_orders if order["side"] == "SELL" and order["status"] == "FILLED"]

            if executed_sell_orders:
                # Ordena as ordens por tempo (timestamp) para obter a mais recente
                last_executed_order = sorted(
                    executed_sell_orders,
                    key=lambda x: x["time"],
                    reverse=True,
                )[0]

                # Retorna o preço da última ordem de venda executada
                last_sell_price = float(last_executed_order["cummulativeQuoteQty"]) / float(last_executed_order["executedQty"])

                # Corrige o timestamp para a chave correta
                datetime_transact = datetime.utcfromtimestamp(last_executed_order["time"] / 1000).strftime("(%H:%M:%S) %d-%m-%Y")

                if verbose:
                    print(f"Última ordem de VENDA executada para {self.operation_code}:")
                    print(
                        f" - Data: {datetime_transact} | Preço: {self.adjust_to_step(last_sell_price,self.tick_size, as_string=True)} | Qnt.: {self.adjust_to_step(float(last_executed_order['origQty']), self.step_size, as_string=True)}"
                    )
                return last_sell_price
            else:
                if verbose:
                    print(f"Não há ordens de VENDA executadas para {self.operation_code}.")
                return 0.0

        except Exception as e:
            if verbose:
                print(f"Erro ao verificar a última ordem de VENDA executada para {self.operation_code}: {e}")
            return 0.0

    def getTimestamp(self):
        """
        Retorna o timestamp ajustado com base no desvio de tempo entre o sistema local e o servidor da Binance.
        """
        try:
            # Obtém o tempo do servidor da Binance e calcula o desvio apenas uma vez
            if (
                not hasattr(
                    self,
                    "time_offset",
                )
                or self.time_offset is None
            ):
                server_time = self.client_binance.get_server_time()["serverTime"]
                local_time = int(time.time() * 1000)
                self.time_offset = server_time - local_time

            # Retorna o timestamp ajustado
            adjusted_timestamp = int(time.time() * 1000) + self.time_offset
            return adjusted_timestamp

        except Exception as e:
            print(f"Erro ao ajustar o timestamp: {e}")
            # Retorna o timestamp local em caso de falha, mas não é recomendado para chamadas críticas
            return int(time.time() * 1000)

    # --------------------------------------------------------------
    # SETs

    # Seta o step_size (para quantidade) e tick_size (para preço) do ativo operado, só precisa ser executado 1x
    def setStepSizeAndTickSize(self):
        # Obter informações do símbolo para respeitar os filtros
        symbol_info = self.client_binance.get_symbol_info(self.operation_code)
        price_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "PRICE_FILTER")
        self.tick_size = float(price_filter["tickSize"])

        lot_size_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "LOT_SIZE")
        self.step_size = float(lot_size_filter["stepSize"])

    """
    Ajusta o valor para o múltiplo mais próximo do passo definido, lidando com problemas de precisão
    e garantindo que o resultado não seja retornado em notação científica.

    Parameters:
        value (float): O valor a ser ajustado.
        step (float): O incremento mínimo permitido.
        as_string (bool): Define se o valor ajustado será retornado como string. Padrão é True.

    Returns:
        str|float: O valor ajustado no formato especificado.
    """

    def adjust_to_step(
        self,
        value,
        step,
        as_string=False,
    ):

        if step <= 0:
            raise ValueError("O valor de 'step' deve ser maior que zero.")

        # Descobrir o número de casas decimais do step
        decimal_places = (
            max(
                0,
                abs(int(math.floor(math.log10(step)))),
            )
            if step < 1
            else 0
        )

        # Ajustar o valor ao step usando floor
        adjusted_value = math.floor(value / step) * step

        # Garantir que o resultado tenha a mesma precisão do step
        adjusted_value = round(
            adjusted_value,
            decimal_places,
        )

        # Retornar no formato especificado
        if as_string:
            return f"{adjusted_value:.{decimal_places}f}"
        else:
            return adjusted_value

    # --------------------------------------------------------------
    # PRINTS

    # Printa toda a carteira
    def printWallet(self):
        for stock in self.account_data["balances"]:
            if float(stock["free"]) > 0:
                print(stock)

    # Printa o ativo definido na classe
    def printStock(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                print(stock)

    def printBrl(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == "BRL":
                print(stock)

    # Printa todas ordens abertas
    def printOpenOrders(self):
        # Log das ordens abertas
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

    # --------------------------------------------------------------
    # GETs auxiliares

    # Retorna toda a carteira
    def getWallet(self):
        for stock in self.account_data["balances"]:
            if float(stock["free"]) > 0:
                return stock

    # Retorna todo o ativo definido na classe
    def getStock(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                return stock
    
    def hasEnoughBalanceToBuy(self, quantity, price):
        """
        Verifica se há saldo suficiente em USDT para realizar a compra.
        """
        try:
            usdt_balance = 0.0
            for asset in self.account_data["balances"]:
                if asset["asset"] == "USDT":
                    usdt_balance = float(asset["free"])
                    break

            required_amount = float(quantity) * float(price)

            if usdt_balance >= required_amount:
                return True
            else:
                print(f"⚠️ Saldo USDT insuficiente.")
                print(f" - Necessário: {required_amount:.2f} USDT")
                print(f" - Disponível: {usdt_balance:.2f} USDT")
                return False

        except Exception as e:
            print(f"Erro ao verificar saldo USDT: {e}")
            return False

    def getPriceChangePercentage(self, initial_price, close_price):

        if initial_price <= 0:
            return 0

        percentual_change = ((close_price - initial_price) / initial_price) * 100

        return percentual_change

    # --------------------------------------------------------------
    # FUNÇÕES DE COMPRA

    # Compra a ação a MERCADO
    def buyMarketOrder(
    self,
    quantity=None,
    score=0,
    probability=0,
    sweep_signal=None,
    trap_signal=None,
    whale_signal=None,
    volume_spike=False
    ):

        try:

            close_price = float(self.stock_data["close_price"].iloc[-1])

            if self.actual_trade_position:
                logging.warning("Erro ao comprar: Posição já comprada.")
                print("Erro ao comprar: Posição já comprada.")
                return False

            # -----------------------------------
            # calcular quantidade se não foi passada
            if quantity is None:

                capital_to_use = self.calculateAdaptivePositionSize(
                    score,
                    probability,
                    sweep_signal,
                    trap_signal,
                    whale_signal,
                    volume_spike
                )

                # limite máximo de risco
                capital_to_use = min(capital_to_use, self.capital * 0.6)

                MIN_NOTIONAL = 5

                if capital_to_use < MIN_NOTIONAL:
                    capital_to_use = MIN_NOTIONAL * 1.05

                raw_quantity = capital_to_use / close_price

                quantity = self.adjust_to_step(
                    raw_quantity,
                    self.step_size,
                    as_string=True
                )

            # -----------------------------------
            # verificar saldo
            if not self.hasEnoughBalanceToBuy(float(quantity), close_price):
                print("⏸️ Compra cancelada por saldo insuficiente.")
                return False

            qty_float = float(quantity)

            notional_value = qty_float * close_price

            MIN_NOTIONAL = 5

            if qty_float < self.step_size or notional_value < MIN_NOTIONAL:
                print("⚠️ Quantidade muito pequena para comprar.")
                return False

            # -----------------------------------
            # enviar ordem
            order_buy = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=quantity,
            )

            # -----------------------------------
            # atualizar estado
            self.highest_price_since_entry = close_price
            self.trailing_stop_price = 0
            self.break_even_activated = False

            self.last_trade_time = time.time()

            self.actual_trade_position = True
            self.saveBotState()

            createLogOrder(order_buy)

            print("\nOrdem de COMPRA enviada com sucesso:")
            print(order_buy)

            return order_buy

        except Exception as e:
            logging.error(f"Erro ao executar ordem de compra: {e}")
            print(f"\nErro ao executar ordem de compra: {e}")
            return False
    
    # Compra por um preço máximo (Ordem Limitada)
    # [NOVA] Define o valor usando RSI e Volume Médio
    def buyLimitedOrder(self, quantity=None, price=0):
        close_price = self.stock_data["close_price"].iloc[-1]
        volume = self.stock_data["volume"].iloc[-1]
        avg_volume = self.stock_data["volume"].rolling(window=20).mean().iloc[-1]
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])

        # 🔥 USAR SALDO USDT DISPONÍVEL AUTOMATICAMENTE
        try:
            account = self.getUpdatedAccountData()
            usdt_balance = 0.0

            for asset in account["balances"]:
                if asset["asset"] == "USDT":
                    usdt_balance = float(asset["free"])
                    break

            if usdt_balance <= 0:
                print("⚠️ Saldo USDT insuficiente.")
                print(f" - Disponível: {usdt_balance:.2f} USDT")
                print("⏸️ Compra cancelada por falta de saldo.")
                return False

        except Exception as e:
            print(f"Erro ao obter saldo USDT: {e}")
            return False

        if price == 0:
            if rsi < 30:
                limit_price = close_price - (0.002 * close_price)
            elif volume < avg_volume:
                limit_price = close_price + (0.002 * close_price)
            else:
                limit_price = close_price + (0.005 * close_price)
        else:
            limit_price = price

        # Ajustar preço ao tick size
        limit_price = self.adjust_to_step(limit_price, self.tick_size, as_string=True)

        # 🔒 Usar capital configurado por ativo + margem de segurança
        SAFETY_MARGIN = 0.95

        capital_to_use = min(self.capital, usdt_balance)  # nunca usar mais que saldo real
        usable_balance = capital_to_use * SAFETY_MARGIN

        if quantity is None:
            raw_quantity = usable_balance / float(close_price)
        else:
            raw_quantity = float(quantity)

        # Ajusta para o mínimo notional da Binance
        quantity = self.adjust_quantity_to_min_notional(raw_quantity, close_price)

        # Ajusta para o step size permitido
        quantity = self.adjust_to_step(quantity, self.step_size, as_string=True)

        print(f"Enviando ordem limitada de COMPRA para {self.operation_code}:")
        print(f" - RSI: {rsi}")
        print(f" - Quantidade ajustada: {quantity}")
        print(f" - Close Price: {close_price}")
        print(f" - Preço Limite: {limit_price}")
        
        # 🔒 Verificar saldo antes de enviar ordem
        if not self.hasEnoughBalanceToBuy(float(quantity), close_price):
            print("⏸️ Compra cancelada por falta de saldo.")
            return False

        try:
            order_buy = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_BUY,
                type=ORDER_TYPE_LIMIT,
                timeInForce="GTC",
                quantity=quantity,
                price=limit_price,
            )
            
            self.highest_price_since_entry = close_price
            self.trailing_stop_price = 0.0
            self.break_even_activated = False
            if order_buy and order_buy.get("status") in ["FILLED", "PARTIALLY_FILLED"]:
                self.actual_trade_position = True
            self.partial_tp_index = 0
            print(f"\nOrdem COMPRA limitada enviada com sucesso:")

            if order_buy is not None:
                createLogOrder(order_buy)

            return order_buy

        except Exception as e:
            logging.error(f"Erro ao enviar ordem limitada de COMPRA: {e}")
            print(f"\nErro ao enviar ordem limitada de COMPRA: {e}")
            return False    
        
    def adjust_quantity_to_min_notional(self, quantity, price):
        """
        Ajusta a quantidade para respeitar o mínimo notional da Binance.
        Evita erro: Filter failure: NOTIONAL
        """       
        try:
            info = self.client_binance.get_symbol_info(self.operation_code)
            min_notional = 5  # fallback padrão Binance

            for f in info["filters"]:
                if f["filterType"] == "MIN_NOTIONAL":
                    min_notional = float(f["minNotional"])
                    break

            notional = float(quantity) * float(price)

            if notional < min_notional:
                quantity = min_notional / float(price)

            quantity = self.adjust_to_step(quantity, self.step_size, as_string=False)
            return float(quantity)

        except Exception as e:
            print(f"Erro ao ajustar quantidade mínima: {e}")
            return quantity    
            
    # --------------------------------------------------------------
    # FUNÇÕES DE VENDA

    # Vende a ação a MERCADO
    def sellMarketOrder(self, quantity=None):
        try:
            if self.actual_trade_position:

                close_price = self.stock_data["close_price"].iloc[-1]

                # Se não definida, vende tudo
                if quantity is None:
                    quantity = self.last_stock_account_balance

                # Ajustar ao step size da Binance
                quantity = self.adjust_to_step(quantity, self.step_size, as_string=True)
                qty_float = float(quantity)

                # 🔒 Ignorar poeira após ajuste real
                if qty_float <= 0 or qty_float * close_price < 5:
                    print("⚠️ Valor muito pequeno para venda a mercado. Ignorando...")
                    return False

                order_sell = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity,
                )

                # 🔥 Resultado da operação
                avg_price = float(order_sell["fills"][0]["price"]) if "fills" in order_sell else close_price
                self.printOperationResult(avg_price, qty_float)

                # 🔄 Atualiza saldo real após execução
                self.updateAllData(verbose=False)
                self.saveBotState()
                                
                self.highest_price_since_entry = 0
                self.trailing_stop_price = 0
                self.break_even_activated = False

                remaining_balance = self.last_stock_account_balance

                # Só zera posição se vendeu praticamente tudo
                if remaining_balance * close_price < 5:
                    self.actual_trade_position = False
                    self.scaling_done = False
                else:
                    self.actual_trade_position = True

                createLogOrder(order_sell)

                print("\nOrdem de VENDA a mercado enviada com sucesso:")
                return order_sell

            else:
                logging.warning("Erro ao vender: Posição já vendida.")
                print("\nErro ao vender: Posição já vendida.")
                return False

        except Exception as e:
            logging.error(f"Erro ao executar ordem de venda a mercado: {e}")
            print(f"\nErro ao executar ordem de venda a mercado: {e}")
            return False

    # Venda por um preço mínimo (Ordem Limitada)
    def sellLimitedOrder(self, price=0):
        close_price = self.stock_data["close_price"].iloc[-1]
        volume = self.stock_data["volume"].iloc[-1]
        avg_volume = self.stock_data["volume"].rolling(window=20).mean().iloc[-1]
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])

        if price == 0:

            momentum = (close_price - self.stock_data["close_price"].iloc[-2]) / self.stock_data["close_price"].iloc[-2]

            # mercado forte → vender mais caro
            if momentum > 0.002 and volume > avg_volume:

                limit_price = close_price + (0.004 * close_price)

            # RSI alto → possível topo
            elif rsi > 70:

                limit_price = close_price + (0.002 * close_price)

            # volume fraco → saída rápida
            elif volume < avg_volume:

                limit_price = close_price - (0.002 * close_price)

            # padrão
            else:

                limit_price = close_price + (0.001 * close_price)

        # Ajustar quantidade ao step
        quantity = self.adjust_to_step(
            self.last_stock_account_balance,
            self.step_size,
            as_string=True,
        )

        # 🔒 PROTEÇÃO CONTRA POEIRA (CRÍTICO)
        if float(quantity) <= 0:
            print("⚠️ Quantidade inválida (poeira). Ignorando venda limitada.")
            return False

        if float(quantity) * float(close_price) < 5:
            print("⚠️ Valor muito pequeno (<5 USDT). Ignorando venda limitada.")
            return False

        print(f"\nEnviando ordem limitada de VENDA para {self.operation_code}:")
        print(f" - RSI: {rsi}")
        print(f" - Quantidade: {quantity}")
        print(f" - Close Price: {close_price}")
        print(f" - Preço Limite: {limit_price}")

        min_acceptable_price = self.getMinimumPriceToSell()

        if float(close_price) <= float(min_acceptable_price):
            print("🚨 Mercado abaixo do preço mínimo aceitável. Executando venda a mercado!")
            self.cancelAllOrders()
            time.sleep(1)
            return self.sellMarketOrder()

        try:
            order_sell = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_SELL,
                type=ORDER_TYPE_LIMIT,
                timeInForce="GTC",
                quantity=quantity,
                price=limit_price,
            )
            
            avg_price = float(limit_price)
            self.printOperationResult(avg_price, float(quantity))

            print(f"\nOrdem VENDA limitada enviada com sucesso:")
            createLogOrder(order_sell)
            return order_sell

        except Exception as e:
            logging.error(f"Erro ao enviar ordem limitada de VENDA: {e}")
            print(f"\nErro ao enviar ordem limitada de VENDA: {e}")
            return False

    # --------------------------------------------------------------
    # ORDENS E SUAS ATUALIZAÇÕES

    # Verifica as ordens ativas do ativo atual configurado
    def getOpenOrders(self):
        open_orders = self.client_binance.get_open_orders(symbol=self.operation_code)

        return open_orders

    # Cancela uma ordem a partir do seu ID
    def cancelOrderById(
        self,
        order_id,
    ):
        self.client_binance.cancel_order(
            symbol=self.operation_code,
            orderId=order_id,
        )
        
    # Cancela todas ordens abertas
    def cancelAllOrders(self):
        if self.open_orders:
            for order in self.open_orders:
                try:
                    self.client_binance.cancel_order(
                        symbol=self.operation_code,
                        orderId=order["orderId"],
                    )
                    print(f"❌ Ordem {order['orderId']} cancelada.")
                except Exception as e:
                    print(f"Erro ao cancelar ordem {order['orderId']}: {e}")   
    
    
    def hasOpenBuyOrder(self):
        """
        Verifica se há uma ordem de compra aberta para o ativo configurado.
        Se houver:
            - Salva a quantidade já executada em self.partial_quantity_discount.
            - Salva o maior preço parcialmente executado em self.last_buy_price.
        """
        # Inicializa as variáveis de desconto e maior preço como 0
        self.partial_quantity_discount = 0.0
        try:

            # Obtém todas as ordens abertas para o par
            open_orders = self.client_binance.get_open_orders(symbol=self.operation_code)

            # Filtra as ordens de compra (SIDE_BUY)
            buy_orders = [order for order in open_orders if order["side"] == "BUY"]

            if buy_orders:
                self.last_buy_price = 0.0

                print(f"\nOrdens de compra abertas para {self.operation_code}:")
                for order in buy_orders:
                    executed_qty = float(order["executedQty"])  # Quantidade já executada
                    price = float(order["price"])  # Preço da ordem

                    print(
                        f" - ID da Ordem: {order['orderId']}, Preço: {price}, Qnt.: {order['origQty']}, Qnt. Executada: {executed_qty}"
                    )

                    # Atualiza a quantidade parcial executada
                    self.partial_quantity_discount += executed_qty

                    # Atualiza o maior preço parcialmente executado
                    if executed_qty > 0 and price > self.last_buy_price:
                        self.last_buy_price = price

                print(f" - Quantidade parcial executada no total: {self.partial_quantity_discount}")
                print(f" - Maior preço parcialmente executado: {self.last_buy_price}")
                return True
            else:
                print(f" - Não há ordens de compra abertas para {self.operation_code}.")
                return False

        except Exception as e:
            print(f"Erro ao verificar ordens abertas para {self.operation_code}: {e}")
            return False
    
    # Verifica se há uma ordem de VENDA aberta para o ativo configurado.
    # Se houver, salva a quantidade já executada na variável self.partial_quantity_discount.
    def hasOpenSellOrder(self):
        # Inicializa a variável de desconto como 0
        self.partial_quantity_discount = 0.0
        try:

            # Obtém todas as ordens abertas para o par
            open_orders = self.client_binance.get_open_orders(symbol=self.operation_code)

            # Filtra as ordens de venda (SIDE_SELL)
            sell_orders = [order for order in open_orders if order["side"] == "SELL"]

            if sell_orders:
                print(f"\nOrdens de venda abertas para {self.operation_code}:")
                for order in sell_orders:
                    executed_qty = float(order["executedQty"])  # Quantidade já executada
                    print(
                        f" - ID da Ordem: {order['orderId']}, Preço: {order['price']}, Qnt.: {order['origQty']}, Qnt. Executada: {executed_qty}"
                    )

                    # Atualiza a quantidade parcial executada
                    self.partial_quantity_discount += executed_qty

                print(f" - Quantidade parcial executada no total: {self.partial_quantity_discount}")
                return True
            else:
                print(f" - Não há ordens de venda abertas para {self.operation_code}.")
                return False

        except Exception as e:
            print(f"Erro ao verificar ordens abertas para {self.operation_code}: {e}")
            return False

    # Função que executa estratégias implementadas e retorna a decisão final
    def getFinalDecisionStrategy(self):

        
        print("🚨 getFinalDecisionStrategy CHAMADA")
        
        print("📈 Rodando estratégia principal...")
        
        final_decision = StrategyRunner.execute(
            self,
            stock_data=self.stock_data,
            main_strategy=self.main_strategy,
            main_strategy_args=self.main_strategy_args,
            fallback_strategy=self.fallback_strategy,
            fallback_strategy_args=self.fallback_strategy_args,
        )

        return final_decision

    # Define o valor mínimo para vender, baseado no acceptable_loss_percentage
    def getMinimumPriceToSell(self):
        return self.last_buy_price * (1 - self.acceptable_loss_percentage)

    # Estratégia de venda por "Stop Loss"
    def stopLossTrigger(self):
        close_price = self.stock_data["close_price"].iloc[-1]
        weighted_price = self.stock_data["close_price"].iloc[-2]  # Preço ponderado pelo candle anterior
        stop_loss_price = self.last_buy_price * (1 - self.stop_loss_percentage)

        print(f'\n - Preço atual: {self.stock_data["close_price"].iloc[-1]}')
        print(f" - Preço mínimo para vender: {self.getMinimumPriceToSell()}")
        print(f" - Stop Loss em: {stop_loss_price:.4f} (-{self.stop_loss_percentage*100:.2f}%)\n")

        if close_price < stop_loss_price and weighted_price < stop_loss_price and self.actual_trade_position == True:
            print("🔴 Ativando STOP LOSS...")
            self.cancelAllOrders()
            time.sleep(2)
            self.sellMarketOrder()
            return True
        return False

    # Estratégia de venda por "Take Profit"
    def takeProfitTrigger(self):
        """
        Verifica se o preço atual atingiu uma meta de take profit e, se sim,
        realiza uma venda parcial da carteira de acordo com os percentuais definidos.
        Retorna True se a venda for executada, caso contrário, retorna False.
        """

        try:
            # Obtém o preço de fechamento mais recente
            close_price = self.stock_data["close_price"].iloc[-1]

            # Calcula a variação percentual do preço
            price_percentage_variation = self.getPriceChangePercentage(initial_price=self.last_buy_price, close_price=close_price)

            print(f" - Variação atual: {price_percentage_variation:.2f}%")
            
            # 🔒 Ignorar se posição virou "poeira" (< 5 USDT)
            if self.last_stock_account_balance * close_price < 5:
                print("⚠️ Posição muito pequena para Take Profit. Ignorando...")
                return False

            # Verifica se o índice atual está dentro do tamanho da lista de take profit
            if self.take_profit_index < len(self.take_profit_at_percentage):
                tp_percentage = self.take_profit_at_percentage[self.take_profit_index]
                tp_amount = self.take_profit_amount_percentage[self.take_profit_index]

                print(f" - Próxima meta Take Profit: {tp_percentage}% (Venda de: {tp_amount}%)\n")

                # Condição para ativação do take profit
                if (
                    self.actual_trade_position  # Só executa se estiver comprado
                    and tp_percentage > 0  # Apenas se o TP for maior que 0
                    and round(price_percentage_variation, 2) >= round(tp_percentage, 2)  # Se atingiu a meta de lucro
                ):
                    # Define a quantidade a ser vendida proporcionalmente
                    quantity_to_sell = self.last_stock_account_balance * (tp_amount / 100)

                    # Verifica se há uma quantidade válida para vender
                    if quantity_to_sell > 0:
                        log = (
                            f"🎯 Meta de Take Profit atingida! ({tp_percentage}% lucro)\n"
                            f" - Vendendo {tp_amount}% da carteira...\n"
                            f" - Preço atual: {close_price:.4f}\n"
                            f" - Quantidade vendida: {quantity_to_sell:.6f} {self.stock_code}"
                        )

                        print(log)
                        logging.info(log)

                        # Tenta executar a venda
                        order_result = self.sellMarketOrder(quantity=quantity_to_sell)

                        # Verifica se a ordem foi executada com sucesso
                        if order_result and "status" in order_result and order_result["status"] == "FILLED":
                            self.take_profit_index += 1
                            print(f"✅ Take Profit {tp_percentage}% realizado com sucesso! Avançando para a próxima meta.")
                            return True  # 🚀 Retorna True indicando que o take profit foi executado

                        else:
                            print(f"❌ Falha ao executar a ordem de venda. Tentando novamente na próxima rodada.")
                            return False  # Falhou na venda, retorna False

                    else:
                        print("⚠️ Quantidade de venda inválida. Take profit não executado.")
                        return False  # Retorna False pois não conseguiu executar a venda

            else:
                print("ℹ️ Todas as metas de take profit já foram atingidas.")
                return False  # Retorna False se todas as metas já foram atingidas

        except Exception as e:
            logging.error(f"Erro no take profit: {e}")
            print(f"❌ Erro no take profit: {e}")
            return False  # Retorna False se houver erro

    # --------------------------------------------------------------

    def isMarketSideways(self, lookback=20, threshold=0.012):
        """
        Detecta lateralização usando range percentual.
        threshold = 1.2% (ideal para seguidor de tendência em cripto 5m)
        """
        closes = self.stock_data["close_price"].iloc[-lookback:]
        max_price = closes.max()
        min_price = closes.min()

        range_pct = (max_price - min_price) / min_price

        print(f"📊 Range lateral: {range_pct*100:.2f}%")

        if range_pct < threshold:
            print("🟡 Mercado lateral detectado.")
            return True
        else:
            print("📈 Mercado com movimento direcional.")
            return False

    # Não usada por enquanto
    def create_order(
        self,
        _symbol,
        _side,
        _type,
        _quantity,
        _timeInForce=None,
        _limit_price=None,
        _stop_price=None,
    ):
        order_buy = TraderOrder.create_order(
            self.client_binance,
            _symbol=_symbol,
            _side=_side,  # Compra
            _type=_type,  # Ordem Limitada
            _timeInForce=_timeInForce,  # Good 'Til Canceled (Ordem válida até ser cancelada)
            _quantity=_quantity,
            _limit_price=_limit_price,
            _stop_price=_stop_price,
        )

        return order_buy

    # Função principal e a única que deve ser executada em loop, quando o
    def execute(self):
                      
        try:
                
                # atualizar scanner somente quando necessário
            if time.time() - self.last_scan_time > self.scan_interval:

                print("🔎 Escaneando mercado inteligente PRO...")

                self.scanner_ranking = self.fastMarketScanner()

                self.last_scan_time = time.time()  
                
            ranking_original = self.scanner_ranking[:5] if self.scanner_ranking else []

            # ativos institucionais prioritários
            smart_money_assets = [
                ("BTCUSDT", 10, 0, 0),
                ("ETHUSDT", 9, 0, 0)
            ]

            ranking = smart_money_assets + ranking_original

            if not ranking:
                print("⚠️ Nenhum ativo encontrado no scanner.")
                return

            # remover duplicados pelo símbolo
            unique = {}
            for r in ranking:
                symbol = r[0]
                if symbol not in unique:
                    unique[symbol] = r

            ranking = list(unique.values())

            tested_symbols = set()
            selected_symbol = None

            for symbol, score, change, volume in ranking:

                if symbol in tested_symbols:
                    continue

                self.resetForNewSymbol()

                print(f"🎯 Testando ativo: {symbol}")

                self.operation_code = symbol

                if not self.updateAllData(verbose=True):
                    continue

                if self.stock_data is None or len(self.stock_data) < 50:
                    continue

                tested_symbols.add(symbol)

                momentum = self.detectMomentumAcceleration()
                volume_spike = self.detectPump()

                if momentum or volume_spike:
                    selected_symbol = symbol
                    break


            if not selected_symbol:
                print("⚠️ Nenhum ativo com momentum encontrado.")
                return    
            
            if self.actual_trade_position:
                profit, pct = self.getCurrentOperationProfit()
                print(f"📊 Posição aberta | PnL: {profit:.4f} USDT ({pct:.2f}%)")
            
            #resetar contador por hora    
            current_hour = datetime.now().hour

            if current_hour != self.last_hour:
                self.hourly_trades = 0
                self.last_hour = current_hour

                       
            print("------------------------------------------------")
            print(f"🟢 Executado {datetime.now().strftime('(%H:%M:%S) %d-%m-%Y')}\n")
            
            # 1️⃣ filtro rápido
            if not self.fastMarketFilter():
                return

            # 2️⃣ análise intermediária
            if not self.mediumMarketAnalysis():
                return

            # 3️⃣ análise pesada
            institutional_signals = self.heavyMarketAnalysis()         
        
            # proteção contra poucos candles
            if self.stock_data is None or len(self.stock_data) < 50:
                print("⚠️ Dados insuficientes de candles.")
                return 
            
            momentum_acceleration = self.detectMomentumAcceleration()            
            momentum_expansion = self.detectMomentumExpansion()            
            volume_divergence = self.detectVolumeDivergence()
            
            close_price = self.stock_data["close_price"].iloc[-1]
            position_value = self.last_stock_account_balance * close_price
                    
            # 🔎 Detectar regime de mercado
            regime = self.detectMarketRegime()
            
            explosion_setup = self.detectVolatilityExplosionSetup()
            
            volume_spike = self.detectPump()
            pump_signal = volume_spike
            
            pre_pump_signal = self.detectPrePump()
            
            accumulation_signal = self.detectSilentAccumulation()
            
            iceberg_signal = self.detectIcebergOrders()
            
            sweep_signal = self.detectLiquiditySweepReversal()
            whale_signal = self.detectWhalePressure()
            
            multi_trend_ok = self.getTrendMultiTimeframe()
            
            if self.actual_trade_position:
                
                self.scalePosition()
                
                if self.trailingStopTrigger():
                    return
                
                # ⚡ SAÍDA POR PERDA DE MOMENTUM
                if not momentum_acceleration:

                    profit, pct = self.getCurrentOperationProfit()

                    if pct < 0.3:

                        print("⚡ Momentum morreu → saída antecipada")

                       

                        # posição pequena demais → limpar estado
                        if position_value < 5:
                            print("🧹 Posição virou poeira. Limpando estado do bot.")

                            self.cancelAllOrders()

                            self.actual_trade_position = False
                            self.last_stock_account_balance = 0
                            self.saveBotState()

                            return

                        self.cancelAllOrders()
                        time.sleep(1)
                        self.sellMarketOrder()

                        return
            
                # detectar divergência de volume
                volume_divergence = self.detectVolumeDivergence()

                if self.detectPumpExhaustion() or volume_divergence:

                    if volume_divergence:
                        print("⚠️ Divergência de volume detectada → saída antecipada")

                    else:
                        print("📉 Pump perdendo força → saindo da posição")

                    self.cancelAllOrders()
                    time.sleep(1)
                    self.sellMarketOrder()

                    return    

                if self.detectWhaleExit():

                    print("🐋 Baleias vendendo → saída antecipada")

                    self.cancelAllOrders()
                    time.sleep(1)
                    self.sellMarketOrder()

                    return    

                trade_duration = time.time() - self.last_trade_time

                # 20 minutos
                if trade_duration > 1200:

                    profit, pct = self.getCurrentOperationProfit()

                    if pct < 0.3:
                        print("⏰ Trade sem progresso. Saindo...")
                        self.sellMarketOrder()
                        return

            # break even
            if self.breakEvenTrigger():
                return
            
            if self.partialTakeProfitHybrid():
                return
            
            # filtro de volume mínimo
            avg_volume = self.stock_data["volume"].iloc[-20:].mean()

            quote_volume = self.stock_data["close_price"] * self.stock_data["volume"]

            avg_quote_volume = quote_volume.iloc[-20:].mean()

            #filtro de liquidez
            if avg_quote_volume < 8000 and not self.actual_trade_position:
                print("⚠️ Liquidez em USDT muito baixa.")
                return 
            

            # 🧹 Limpeza automática de poeira
            self.cleanDustPosition()
               
            self.updateDailyProfit()
            
            # 💰 rebalance automático de lucro
            self.rebalance_profit(self.daily_profit)
            
            # 🛑 Stop diário de perda
            if self.daily_profit <= -self.max_daily_loss:
                print("🛑 Stop diário de perda atingido.")
                return

            # 🚫 Limite de trades diário
            if self.daily_trades >= self.max_daily_trades:
                print("🚫 Limite diário atingido.")
                return

            smart_money_signal = self.detectSmartMoneyAccumulation()

            if smart_money_signal and not self.actual_trade_position:

                print("🏦 Entrada antecipada Smart Money")

                self.buyMarketOrder()

                return

            # 🚀 Entrada antecipada (pré-pump)
            if pre_pump_signal and not self.actual_trade_position and regime in ["TREND", "EXPLOSIVE"]:

                # 💣 Entrada antecipada por compressão + volume
                if explosion_setup and not self.actual_trade_position:

                    print("💥 ENTRADA POR COMPRESSÃO DE VOLATILIDADE")

                    price = self.stock_data["close_price"].iloc[-1]

                    capital_to_use = self.capital * 0.6

                    quantity = capital_to_use / price
                    quantity = self.adjust_to_step(quantity, self.step_size)

                    if quantity > 0:

                        self.buyMarketOrder(quantity=quantity)

                        self.hourly_trades += 1
                        self.last_trade_time = time.time()

                        return

                print("🔥 Entrada antecipada detectada (pré-pump)")

                self.buyMarketOrder()
                self.hourly_trades += 1
                return

            if pump_signal and not self.actual_trade_position and regime == "EXPLOSIVE":
                print("🚀 Pump confirmado em regime explosivo.")
                self.buyMarketOrder()
                return

            # Evita operar em baixa volatilidade
            if self.isLowVolatility() and regime not in ["PRE_BREAKOUT", "EXPLOSIVE"]:
                print("⏸️ Pulando trade por baixa volatilidade.")
                return
            
            orderflow_signal = None
            
            if regime == "SIDEWAYS" and not (
                sweep_signal
                or whale_signal
                or orderflow_signal == "BUY"
            ):
                print("⏸️ Mercado lateral detectado pelo regime.")
                return

            # ---------------------------------------------
            # Detector inteligente: Lateralização + Tendência
            if self.actual_trade_position:

                sideways = self.isMarketSideways()
                
                if sideways:
                    self.sideways_counter += 1
                    print(f"⚠️ Lateralização detectada ({self.sideways_counter}/{self.sideways_limit})")

                    if self.sideways_counter >= self.sideways_limit and not multi_trend_ok:
                        print("🔻 Lateralização persistente + tendência fraca detectada.")

                        if not self.stock_data.empty:
                            close_price = self.stock_data["close_price"].iloc[-1]
                            if close_price <= 0:
                                print("⚠️ Preço inválido.")
                                return  
                              
                            quantity_half = self.last_stock_account_balance * 0.5
                            value_half = quantity_half * close_price

                            self.cancelAllOrders()
                            time.sleep(1)

                            if value_half < 5:
                                print("⚠️ Posição pequena demais para redução parcial. Vendendo 100%...")
                                self.sellMarketOrder()
                            else:
                                print("🔻 Reduzindo posição em 50% por mercado lateral...")
                                self.sellMarketOrder(quantity=quantity_half)

                        self.sideways_counter = 0
                        return
                else:
                    self.sideways_counter = 0

            # 🚀 Detector institucional
            if regime in ["TREND", "EXPLOSIVE"] and self.detectInstitutionalMomentum() and not self.actual_trade_position:

                print("🔥 Entrada institucional antecipada")

                if not self.actual_trade_position:
                    print("🚀 Entrada confirmada.")
                    self.buyMarketOrder()
                    self.hourly_trades += 1

                return

            if not self.btcTrendFilter():
                print("⚠️ BTC em tendência de baixa. Evitando altcoins.")
                return



            # ---------------------------------------------
            # ---------------------------------------------
            # EXECUTAR ESTRATÉGIA   
            
            spread = 0
            signal = None
            
            depth = self.getCachedOrderBook()

            if not depth or not depth["bids"] or not depth["asks"]:
                print("⚠️ Orderbook vazio. Pulando ciclo.")
                return

            orderflow_signal = self.detectOrderFlowImbalance()

            best_bid = float(depth["bids"][0][0])
            best_ask = float(depth["asks"][0][0])

            if best_bid <= 0:
                return

            spread = (best_ask - best_bid) / best_bid
            
            liquidity_signal = self.detectLiquidityWall()

            liquidation_signal = self.detectLiquidationMove()

            # 🔥 DETECTORES
           
            trap_signal = self.detectMarketMakerTrap()
            
            stop_hunt_signal = self.detectStopHunt()
            
            liquidity_trap_signal = self.detectLiquidityTrap()
            
            manipulation_signal = self.detectLiquidityManipulation()
                        
            grab_signal = self.detectLiquidityGrab()

            compression_signal = self.detectVolatilityCompression()
            
            breakout_signal = self.detectRealBreakout()

            spoof_signal = self.detectSpoofing()
            
            vacuum_signal = self.detectLiquidityVacuum()
            
            strategy_signal = self.getFinalDecisionStrategy()
            
            volatility_expansion = self.detectVolatilityExpansion()
            
            momentum_acceleration = self.detectMomentumAcceleration()
            
            delta_signal = self.detectVolumeDelta()
            
            volume_confirm = volume_spike or delta_signal == "BUY"

            recent_range = (
                self.stock_data["close_price"].iloc[-20:].max() -
                self.stock_data["close_price"].iloc[-20:].min()
            ) / self.stock_data["close_price"].iloc[-20:].min()

            tight_compression = recent_range < 0.01
            
            score = 0
            
            # 🚀 Breakout após compressão (setup explosivo) 
            

            if breakout_signal == "BUY":
                score += 3
            
            if accumulation_signal:
                score += 4

            if iceberg_signal:
                score += 3

            if trap_signal:
                score += 3

            if sweep_signal:
                score += 3
            
            if vacuum_signal == "BUY":
                score += 3
                
            if whale_signal == "BUY":
                score += 3

            if volume_spike:
                score += 0.5

            if compression_signal and volatility_expansion:
                score += 2

            if multi_trend_ok:
                score += 2
            
            if volatility_expansion:
                score += 2
                
            if orderflow_signal == "BUY":
                score += 2

            if orderflow_signal == "SELL":
                score -= 1

            if momentum_acceleration:
                score += 2
            
            if momentum_expansion:
                score += 3
            
            if not self.marketRiskFilter():
                return
        
            if delta_signal == "BUY":
                score += 2

            if delta_signal == "SELL":
                score -= 2
            
            print(f"📊 Score de entrada: {score}")
            
            # ---------------------------------------------
            # 🏦 INSTITUTIONAL SCORE (atalho para pumps)

            institutional_score = 0

            if whale_signal == "BUY":
                institutional_score += 2

            if vacuum_signal == "BUY":
                institutional_score += 2

            if orderflow_signal == "BUY":
                institutional_score += 2

            if stop_hunt_signal == "BUY":
                institutional_score += 1

            print(f"🏦 Institutional Score: {institutional_score}")

            # 🚀 Entrada institucional imediata
            if institutional_score >= 5 and not self.actual_trade_position:

                print("🔥 ENTRADA INSTITUCIONAL FORTE DETECTADA")

                price = self.stock_data["close_price"].iloc[-1]

                capital_to_use = self.calculateAdaptivePositionSize(
                    score,
                    0.75,  # probabilidade alta presumida
                    sweep_signal,
                    trap_signal,
                    whale_signal,
                    volume_spike
                )

                quantity = capital_to_use / price
                quantity = self.adjust_to_step(quantity, self.step_size)

                if quantity > 0:

                    self.buyMarketOrder(quantity=quantity)

                    self.hourly_trades += 1
                    self.last_trade_time = time.time()

                    return
            
            probability = self.calculateTradeProbability(
                score,
                regime,
                spread,
                volume_spike
            )
            
            # normalizar sinal
            if strategy_signal in ["Comprar", "BUY", True]:
                signal = "BUY"
            elif strategy_signal in ["Vender", "SELL", False]:
                signal = "SELL"
            else:
                signal = None

            # ---------------------------------------------
            # CONFIRMAÇÃO DE CANDLE

            confirmation = False

            if len(self.stock_data) >= 3:

                last = self.stock_data["close_price"].iloc[-1]
                prev = self.stock_data["close_price"].iloc[-2]

                if last > prev:
                    confirmation = True

            print(f"📊 Estratégia: {signal}")
            print(f"💧 Liquidez: {liquidity_signal}")
            print(f"💥 Liquidação: {liquidation_signal}")
            
            if signal is None:
                print("⚠️ Nenhum sinal da estratégia")
            
            # -----------------------------------------
            # 🚀 EXCEÇÃO INSTITUCIONAL

            if signal == "BUY":

                if score >= 7.5 and probability >= 0.55:

                    print("🔥 Trade institucional forte - ignorando filtros")

                else:

                    if not self.tradeQualityFilter():

                        print("⛔ Trade bloqueado pelo filtro de qualidade")

                        return
            
            # manipulação institucional
            if manipulation_signal:
                print("🏦 Manipulação institucional detectada")
                signal = manipulation_signal
            
            # ------------------------------------------------
            # Ajuste do sinal com detectores institucionais

            # Liquidity Vacuum pode antecipar movimento
            if vacuum_signal == "BUY" and signal != "SELL":
                print("🌪️ Liquidity vacuum reforçando compra")
                signal = "BUY"

            # Baleias vendendo forte
            if whale_signal == "SELL" and signal != "BUY":
                print("🐋 Baleias pressionando venda")
                signal = "SELL"
            
            # ------------------------------------------------
            # 🚀 Atalho institucional (prioridade alta)

            institutional_buy = (
                vacuum_signal == "BUY"
                and orderflow_signal == "BUY"
                and momentum_acceleration
            )

            if institutional_buy and not self.actual_trade_position:
                print("🏦 Entrada institucional detectada")
                signal = "BUY"
                
            elif vacuum_signal == "BUY" and orderflow_signal == "BUY":
                signal = "BUY"
                
            elif whale_signal == "BUY" and momentum_acceleration:
                print("🐋 Baleias + Momentum")
                signal = "BUY"
                            
            else:
                if signal is None:

                    # spoofing (maior prioridade)
                    if spoof_signal:
                        print("⚠️ Spoofing detectado → reduzindo confiança")
                        score -= 2
                    # market maker trap
                    elif trap_signal:
                        signal = trap_signal
                    
                    elif stop_hunt_signal:
                        print("🎯 Stop hunt institucional detectado")
                        signal = stop_hunt_signal
                        
                    elif liquidity_trap_signal:
                        signal = liquidity_trap_signal

                    # stop hunt
                    elif sweep_signal:
                        signal = sweep_signal
                    
                    elif grab_signal:
                        signal = grab_signal

                    elif vacuum_signal:
                        signal = vacuum_signal

                    elif accumulation_signal and multi_trend_ok and not self.actual_trade_position:

                        print("🔥 Sinal de acumulação detectado")

                        signal = "BUY"

                    # institucional
                    elif whale_signal == "BUY" and volume_spike:
                        signal = "BUY"

                    # liquidez
                    elif liquidity_signal:
                        signal = liquidity_signal

                    # liquidação
                    elif liquidation_signal:
                        signal = liquidation_signal
                
                    elif orderflow_signal:
                        print("📊 Ordem Flow dominante detectado")
                        signal = orderflow_signal

                    
            if spread > 0.006:
                print("⚠️ Spread alto. Evitando trade.")
                return
            
            # 🚀 Setup explosivo institucional

            if (
                compression_signal
                and breakout_signal == "BUY"
                and volatility_expansion
                and momentum_acceleration
                and volume_confirm
                and orderflow_signal == "BUY"
                and probability > 0.55
                and spread < 0.002
                and regime in ["PRE_BREAKOUT","EXPLOSIVE"]
                and not self.actual_trade_position
            ):

                print("💥 SETUP EXPLOSIVO DETECTADO")

                price = self.stock_data["close_price"].iloc[-1]

                capital_to_use = self.calculateAdaptivePositionSize(
                    score,
                    probability,
                    sweep_signal,
                    trap_signal,
                    whale_signal,
                    volume_spike
                )

                # proteção mínimo Binance
                min_notional = 5

                if capital_to_use < min_notional:
                    capital_to_use = min_notional * 1.05

                raw_quantity = capital_to_use / price

                quantity = float(self.adjust_to_step(raw_quantity, self.step_size))

                if quantity > 0:

                    print("🚀 Entrada por compressão + breakout")

                    self.buyMarketOrder(quantity=quantity)

                    self.hourly_trades += 1
                    self.last_trade_time = time.time()

                    return
                
            # ---------------------------------------------
            # COMPRA
            institutional_setup = (
                score >= 9
                or (whale_signal == "BUY" and vacuum_signal == "BUY")
            )

            # 🚫 evitar entrada se houver divergência de volume
            if volume_divergence and not self.actual_trade_position:
                print("⚠️ Divergência de volume detectada, evitando compra")
                return    

            if signal in [True, "BUY"] and probability >= 0.45 and regime in ["TREND","EXPLOSIVE","PRE_BREAKOUT"]:

                if not confirmation:
                    print("⏳ Aguardando confirmação do candle")
                    return
                
                recent_high = self.stock_data["close_price"].iloc[-20:].max()
                close_price = self.stock_data["close_price"].iloc[-1]

                distance_from_top = (recent_high - close_price) / close_price

                if distance_from_top < 0.0005:
                    print("⚠️ Muito perto do topo recente")
                    return

                if len(self.stock_data) >= 6:

                    move = (
                        self.stock_data["close_price"].iloc[-1]
                        - self.stock_data["close_price"].iloc[-5]
                    ) / self.stock_data["close_price"].iloc[-5]

                    if move > 0.05:
                        print("⚠️ Movimento já esticado")
                        return

                if institutional_setup and probability >= 0.70:
                    print("🔥 Trade institucional detectado - ignorando filtro")

                else:
                    if not self.tradeQualityFilter():
                        print("⛔ Trade bloqueado pelo filtro de qualidade")
                        return   

                if self.hourly_trades >= self.max_hourly_trades:
                    print("⏸️ Limite de trades por hora atingido.")
                    return     

                # ⏸️ Cooldown entre trades
                if time.time() - self.last_trade_time < self.trade_cooldown and score < 8:
                    print("⏸️ Cooldown ativo. Aguardando próximo trade.")
                    return

                # 🔎 Filtros institucionais antes da entrada
                if self.detectFakeBreakout():
                    print("⚠️ Entrada cancelada: fake breakout")
                    return

                if self.detectAbsorption():
                    print("🏦 Absorção detectada, aguardando confirmação")
                    return
                
                capital_to_use = self.calculateAdaptivePositionSize(
                    score, 
                    probability,
                    sweep_signal,
                    trap_signal,
                    whale_signal,
                    volume_spike
                )
                
                price = self.stock_data["close_price"].iloc[-1]

                if price <= 0:
                    return

                quantity = capital_to_use / price
                quantity = self.adjust_to_step(quantity, self.step_size)

                if quantity <= 0:
                    print("⚠️ Quantidade inválida.")
                    return

                if not self.actual_trade_position:
                    print("🚀 Entrada confirmada.")
                    if regime == "EXPLOSIVE":
                        self.buyMarketOrder(quantity=quantity)
                    else:
                        self.buyLimitedOrder(quantity=quantity)
                    self.hourly_trades += 1
                    self.last_trade_time = time.time()
                                             
            if signal == "SELL" and not self.actual_trade_position:
                print("⚠️ Sinal de venda detectado, mas não há posição aberta.")

            # ---------------------------------------------
            # VENDA
            elif signal == "SELL":

                close_price = self.stock_data["close_price"].iloc[-1]

                if self.actual_trade_position and self.last_stock_account_balance * close_price >= 5:
                    print("⚠️ Saída confirmada.")
                    self.sellMarketOrder()

        except Exception as e:
            print(f"❌ Erro no ciclo do robô: {e}")
                        
    def cleanDustPosition(self):

        try:

            close_price = self.stock_data["close_price"].iloc[-1]
            notional_value = self.last_stock_account_balance * close_price

            if 0 < notional_value < 5:

                print("\n🧹 Poeira detectada na carteira:")
                print(f" - Quantidade: {self.last_stock_account_balance:.8f} {self.stock_code}")
                print(f" - Valor estimado: {notional_value:.4f} USDT")

                self.actual_trade_position = False
                self.last_stock_account_balance = 0.0

            return False

        except Exception as e:
            print(f"Erro ao limpar poeira: {e}")
            return False
                            
    def getCurrentOperationProfit(self):
        """
        Calcula lucro/prejuízo da operação atual (não realizado).
        Retorna: (profit_usdt, profit_percent)
        """
        try:
            if not self.actual_trade_position or self.last_buy_price == 0:
                return 0.0, 0.0

            close_price = self.stock_data["close_price"].iloc[-1]

            # Valor investido
            invested = self.last_stock_account_balance * self.last_buy_price

            # Valor atual da posição
            current_value = self.last_stock_account_balance * close_price

            profit_usdt = current_value - invested
            profit_percent = (profit_usdt / invested) * 100 if invested > 0 else 0

            return profit_usdt, profit_percent

        except Exception as e:
            print(f"Erro ao calcular lucro da operação: {e}")
            return 0.0, 0.0
        
    def updateDailyProfit(self):
        """
        Calcula lucro realizado no dia baseado nas ordens FILLED.
        """
        try:
            today = datetime.now().date()

            # Reset automático ao virar o dia
            if today != self.current_day:
                self.daily_profit = 0.0
                self.daily_trades = 0
                self.last_closed_order_id = None
                self.current_day = today

            if hasattr(self, "daily_orders_cache") and time.time() - self.daily_orders_time < 20:
                orders = self.daily_orders_cache
            else:
                orders = self.client_binance.get_all_orders(
                    symbol=self.operation_code,
                    limit=200
                )
                self.daily_orders_cache = orders
                self.daily_orders_time = time.time()

            # Filtra vendas executadas
            filled_sells = [
                o for o in orders
                if o["side"] == "SELL" and o["status"] == "FILLED"
            ]

            for order in filled_sells:

                order_time = datetime.utcfromtimestamp(order["time"] / 1000).date()

                if order_time == today:

                    order_id = order["orderId"]

                    # evita duplicação
                    if order_id != self.last_closed_order_id:

                        qty = float(order["executedQty"])

                        if qty <= 0:
                            continue

                        sell_value = float(order["cummulativeQuoteQty"])

                        if self.last_buy_price <= 0:
                            continue

                        cost = qty * self.last_buy_price

                        profit = sell_value - cost

                        self.daily_profit += profit
                        self.daily_trades += 1
                        self.last_closed_order_id = order_id

        except Exception as e:
            print(f"Erro ao atualizar lucro diário: {e}")
            
    def printOperationResult(self, sell_price, quantity):

        try:

            if self.last_buy_price == 0:
                return

            entry_price = float(self.last_buy_price)
            exit_price = float(sell_price)
            qty = float(quantity)

            pnl_usdt = (exit_price - entry_price) * qty
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100

            trade = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": self.operation_code,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": qty,
                "profit_usdt": round(pnl_usdt, 6),
                "profit_pct": round(pnl_pct, 4),
                "capital": round(entry_price * qty, 6)
            }

            # histórico em memória
            main.TRADE_HISTORY.append(trade)

            # histórico permanente
            log_trade(trade)

            print("\n💰 RESULTADO DA OPERAÇÃO")
            print(f"Entrada : {entry_price:.4f}")
            print(f"Saída   : {exit_price:.4f}")
            print(f"Qtd     : {qty:.6f}")
            print(f"PnL     : {pnl_usdt:.6f} USDT ({pnl_pct:.2f}%)")

        except Exception as e:
            print("Erro ao calcular PnL:", e)

    def breakEvenTrigger(self):
        """
        Move o stop para o preço de entrada quando lucro atinge o break-even configurado por ativo
        """
        if not self.actual_trade_position or self.last_buy_price == 0:
            return False

        close_price = self.stock_data["close_price"].iloc[-1]
        profit_pct = self.getPriceChangePercentage(self.last_buy_price, close_price)

        # converter break-even para %
        break_even_pct = self.break_even_activation * 100

        # Usa valor configurável por ativo
        if profit_pct >= break_even_pct and not getattr(self, "break_even_activated", False):
            fee_buffer = self.last_buy_price * 0.001  # ~0.1% taxa
            self.trailing_stop_price = self.last_buy_price + fee_buffer
            self.break_even_activated = True
            print("🛡️ Break-even ativado!")

        return False

    def partialTakeProfitHybrid(self):
        """
        Realiza vendas parciais em níveis de lucro e deixa o restante rodar com trailing.
        """
        if not self.actual_trade_position or self.last_buy_price == 0:
            return False

        close_price = self.stock_data["close_price"].iloc[-1]
        profit_pct = self.getPriceChangePercentage(self.last_buy_price, close_price)

        if self.partial_tp_index >= len(self.partial_take_profit_levels):
            return False

        target_pct = self.partial_take_profit_levels[self.partial_tp_index]
        sell_pct = self.partial_take_profit_amounts[self.partial_tp_index]

        print(f"🎯 Parcial alvo: {target_pct}% | Lucro atual: {profit_pct:.2f}%")

        if profit_pct >= target_pct:
            quantity_to_sell = self.last_stock_account_balance * (sell_pct / 100)

            if quantity_to_sell * close_price < 5:
                print("⚠️ Parcial muito pequena (<5 USDT). Ignorando...")
                self.partial_tp_index += 1
                return False

            print(f"💸 Realizando parcial: {sell_pct}% da posição...")
            order = self.sellMarketOrder(quantity=quantity_to_sell)

            if order:
                self.partial_tp_index += 1
                print("✅ Parcial executada. Restante segue com trailing!")
                return True

        return False

    def close_position_market(self):
        """
        Fecha posição atual a mercado usando o saldo real.
        """

        if not self.actual_trade_position:
            print("ℹ️ Nenhuma posição aberta para fechar.")
            return False

        try:
            # 🔄 Atualiza dados antes de fechar
            self.updateAllData(verbose=False)

            close_price = self.stock_data["close_price"].iloc[-1]
            quantity = self.last_stock_account_balance

            # Ajusta ao step da Binance
            quantity = self.adjust_to_step(quantity, self.step_size, as_string=False)

            if float(quantity) * close_price < 5:
                print("⚠️ Valor muito pequeno para fechar posição.")
                return False

            print("🛑 Fechando posição a mercado por encerramento de horário...")

            order = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )

            self.actual_trade_position = False
            createLogOrder(order)

            print("✅ Posição encerrada com sucesso.")
            return order

        except BinanceAPIException as e:
            print("⚠️ Erro Binance:", e)
            time.sleep(5)

        except Exception as e:
            print("❌ Erro inesperado:", e)
            time.sleep(2)

    def detectPump(self):
        
        volume = self.stock_data["volume"].iloc[-1]
        avg_volume = self.stock_data["volume"].rolling(20).mean().iloc[-1]

        close = self.stock_data["close_price"].iloc[-1]
        if len(self.stock_data) < 2:
            return False
        prev = self.stock_data["close_price"].iloc[-2]

        if prev == 0 or avg_volume == 0:
            return False

        price_change = (close - prev) / prev

        if volume > avg_volume * 2 and price_change > 0.001:

            print("🚀 POSSÍVEL PUMP DETECTADO")

            return True

        return False
    
    def detectPrePump(self):

        try:

            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 30:
                return False

            current_price = closes.iloc[-1]
            prev_price = closes.iloc[-2]

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            # crescimento de volume
            volume_growth = current_volume > avg_volume * 1.8

            # movimento ainda pequeno
            price_change = abs((current_price - prev_price) / prev_price)

            # compressão de preço
            recent_range = (closes.iloc[-20:].max() - closes.iloc[-20:].min()) / closes.iloc[-20:].min()

            # pressão compradora
            buy_pressure = current_price > prev_price

            if volume_growth and price_change < 0.01 and recent_range < 0.015 and buy_pressure:

                print("🚀 POSSÍVEL PRÉ-PUMP DETECTADO")

                print(f"Volume growth: {current_volume/avg_volume:.2f}x")
                print(f"Price change: {price_change*100:.2f}%")

                return True

            return False

        except Exception as e:

            print("Erro no detector de pré-pump:", e)

            return False

    def isLowVolatility(self):

        try:

            closes = self.stock_data["close_price"]
            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]

            # Range do mercado
            recent_range = (closes.iloc[-20:].max() - closes.iloc[-20:].min()) / closes.iloc[-20:].min()

            # ATR simplificado
            true_ranges = (highs - lows)
            atr = true_ranges.rolling(14).mean().iloc[-1]

            atr_pct = atr / closes.iloc[-1]

            print(f"📊 Range 20 candles: {recent_range*100:.2f}%")
            print(f"📊 ATR: {atr_pct*100:.2f}%")

            if recent_range < self.min_volatility * 1.2 and atr_pct < self.min_volatility:

                print("⚠️ Mercado realmente sem volatilidade.")

                return True
            
            if atr_pct > self.max_volatility:
                print("⚠️ Volatilidade excessiva. Evitando trade.")
                return True

            return False
        
        except Exception as e:

            print("Erro ao calcular volatilidade:", e)

            return False

    def detectLiquidationMove(self):

        volume = self.stock_data["volume"].iloc[-1]
        
        if len(self.stock_data) < 30:
            return False
        
        avg_volume = self.stock_data["volume"].rolling(20).mean().iloc[-1]

        close = self.stock_data["close_price"].iloc[-1]
        
        if len(self.stock_data) < 2:
            return None
        
        prev = self.stock_data["close_price"].iloc[-2]

        if prev == 0:
            return None
        price_change = (close - prev) / prev

        if volume > avg_volume * 3 and abs(price_change) > 0.01:

            print("💥 Liquidação detectada")

            if price_change > 0:
                return "BUY"
            else:
                return "SELL"

        return None    
    
    def detectInstitutionalMomentum(self):

        try:

            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            current_price = closes.iloc[-1]

            avg_volume = volumes.rolling(20).mean().iloc[-1]
            current_volume = volumes.iloc[-1]

            if len(closes) < 30:
                return False
            
            recent_high = closes.iloc[-30:-1].max()

            volume_spike = avg_volume > 0 and current_volume > avg_volume * 2
            breakout = current_price >= recent_high * 0.999

            price_momentum = (current_price - closes.iloc[-2]) / closes.iloc[-2]

            trend = closes.iloc[-1] > closes.rolling(20).mean().iloc[-1]

            if volume_spike and breakout and price_momentum > 0.003 and trend:

                print("🚀 MOMENTUM INSTITUCIONAL DETECTADO")

                print(f"Volume spike: {current_volume / avg_volume:.2f}x")
                print(f"Breakout nível: {recent_high}")

                return True

            return False

        except Exception as e:

            print("Erro no detector institucional:", e)

            return False
    
    def detectWhalePressure(self):

        try:

            bids, asks = self.getSafeOrderBook()

            if not bids or not asks:
                return None

            bid_volume = sum(float(b[1]) for b in bids[:10])
            ask_volume = sum(float(a[1]) for a in asks[:10])

            imbalance = bid_volume / ask_volume if ask_volume > 0 else 0

            print(f"🐋 Pressão de compra: {bid_volume}")
            print(f"🐋 Pressão de venda : {ask_volume}")
            print(f"⚖️ Imbalance: {imbalance:.2f}")

            if imbalance > 1.6:
                print("🚀 Baleias comprando forte!")
                return "BUY"

            if imbalance < 0.6:
                print("🔻 Baleias vendendo forte!")
                return "SELL"

            return None

        except Exception as e:

            print("Erro no detector de baleias:", e)

            return None
        
    def detectLiquidityWall(self):

        try:

            bids, asks = self.getSafeOrderBook()

            if not bids or not asks:
                return

            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])

            if not bids or not asks:
                print("⚠️ Orderbook vazio. Ignorando detector de liquidez.")
                return None

            bid_wall = max(float(b[1]) for b in bids[:15])
            ask_wall = max(float(a[1]) for a in asks[:15])

            print(f"💧 Maior parede de compra: {bid_wall}")
            print(f"💧 Maior parede de venda : {ask_wall}")

            if bid_wall > ask_wall * 2:
                print("🟢 Parede forte de COMPRA detectada")
                return "BUY"

            if ask_wall > bid_wall * 2:
                print("🔴 Parede forte de VENDA detectada")
                return "SELL"

            return None

        except Exception as e:

            print("Erro no detector de liquidez:", e)
            return None
        
    def getCachedOrderBook(self):

        try:

            with self.lock:

                if self.cached_orderbook and time.time() - self.last_orderbook_check < 8:
                    return self.cached_orderbook

                depth = self.client_binance.get_order_book(
                    symbol=self.operation_code,
                    limit=50
                )

                self.cached_orderbook = depth
                self.last_orderbook_check = time.time()

                return depth

        except Exception as e:
            print("Erro ao obter orderbook:", e)

            if self.cached_orderbook:
                return self.cached_orderbook

            return {"bids": [], "asks": []}
        
    def detectMarketRegime(self):

        closes = self.stock_data["close_price"]
        highs = self.stock_data["high_price"]
        lows = self.stock_data["low_price"]
        volumes = self.stock_data["volume"]

        ma20 = closes.rolling(20).mean().iloc[-1]
        ma50 = closes.rolling(50).mean().iloc[-1]

        recent_range = (closes.iloc[-20:].max() - closes.iloc[-20:].min()) / closes.iloc[-20:].min()

        avg_volume = volumes.rolling(20).mean().iloc[-1]
        current_volume = volumes.iloc[-1]

        atr = (highs - lows).rolling(14).mean().iloc[-1]
        atr_pct = atr / closes.iloc[-1]

        compression = self.detectVolatilityCompression()
        momentum = self.detectMomentumAcceleration()

        if compression and momentum:

            print("⚡ REGIME: PRE-BREAKOUT")

            return "PRE_BREAKOUT"

        if current_volume > avg_volume * 2 and atr_pct > 0.004:

            print("🔥 REGIME: EXPLOSIVO")

            return "EXPLOSIVE"

        if abs(ma20 - ma50) / closes.iloc[-1] > 0.002:

            print("📈 REGIME: TREND")

            return "TREND"

        if recent_range < 0.006:

            print("↔️ REGIME: SIDEWAYS")

            return "SIDEWAYS"

        return "NORMAL"

    def detectFakeBreakout(self):

        closes = self.stock_data["close_price"]

        breakout = closes.iloc[-1] > closes.iloc[-20:-1].max()

        volume = self.stock_data["volume"].iloc[-1]
        avg_volume = self.stock_data["volume"].rolling(20).mean().iloc[-1]

        if breakout and volume < avg_volume:
            print("⚠️ POSSÍVEL FAKE BREAKOUT")
            return True

        return False

    def detectAbsorption(self):

        closes = self.stock_data["close_price"]
        volumes = self.stock_data["volume"]

        candle = abs(closes.iloc[-1] - closes.iloc[-2])
        volume = volumes.iloc[-1]
        avg_volume = volumes.rolling(20).mean().iloc[-1]

        if volume > avg_volume * 3 and candle < closes.iloc[-1] * 0.001:
            print("🏦 ABSORÇÃO INSTITUCIONAL DETECTADA")
            return True

        return False
    
    def detectLiquiditySweepReversal(self):
        """
        Detecta varredura de liquidez (stop hunt) seguida de reversão.
        Retorna "BUY", "SELL" ou None.
        """
        try:
            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]
            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 20:
                return None

            recent_low = lows.iloc[-2]
            previous_low = lows.iloc[-10:-2].min()

            recent_high = highs.iloc[-2]
            previous_high = highs.iloc[-10:-2].max()

            close = closes.iloc[-1]
            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            # Sweep de fundo → possível reversão de alta
            if recent_low < previous_low and close > previous_low and current_volume > avg_volume * 1.2:
                print("🧹 Liquidity sweep detectado no fundo (stop hunt)")
                return "BUY"

            # Sweep de topo → possível reversão de baixa
            if recent_high > previous_high and close < previous_high and current_volume > avg_volume * 1.2:
                print("🧹 Liquidity sweep detectado no topo (stop hunt)")
                return "SELL"

            return None

        except Exception as e:
            print("Erro no detector de liquidity sweep:", e)
            return None
    
    def detectSpoofing(self):

        try:

            depth = self.getCachedOrderBook()

            bids = depth.get("bids", [])[:10]
            asks = depth.get("asks", [])[:10]

            if not bids or not asks:
                return False

            bid_volume = sum(float(b[1]) for b in bids)
            ask_volume = sum(float(a[1]) for a in asks)

            max_bid = max(float(b[1]) for b in bids)
            max_ask = max(float(a[1]) for a in asks)

            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])

            print(f"🕵️ Spoofing check - bid wall: {max_bid} | ask wall: {max_ask}")

            min_wall_size = 0.5

            bid_spoof = (
                max_bid > bid_volume * 0.6
                and max_bid > min_wall_size
            )

            ask_spoof = (
                max_ask > ask_volume * 0.6
                and max_ask > min_wall_size
            )

            if bid_spoof or ask_spoof:
                print("⚠️ Possível spoofing detectado")
                return True

            return False

        except Exception as e:

            print("Erro no detector de spoofing:", e)
            return False
            
    def detectLiquidityVacuum(self):
        """
        Detecta vácuo de liquidez no orderbook.
        Quando há pouca liquidez perto do preço atual,
        o mercado tende a se mover rapidamente.
        """

        try:

            bids, asks = self.getSafeOrderBook()
            
            if not bids or not asks:
                return None

            bid_volume = sum(float(b[1]) for b in bids)
            ask_volume = sum(float(a[1]) for a in asks)

            if self.stock_data.empty:
                return None

            total_liquidity = bid_volume + ask_volume

            print(f"🌪️ Liquidity Vacuum check: {total_liquidity:.4f}")

            # Liquidez muito baixa
            if total_liquidity < 1000:

                print("🌪️ Vácuo de liquidez detectado!")

                # direção baseada em imbalance
                if bid_volume > ask_volume:
                    print("🚀 Possível pump por falta de liquidez")
                    return "BUY"

                elif ask_volume > bid_volume:
                    print("🔻 Possível dump por falta de liquidez")
                    return "SELL"

            return None

        except Exception as e:

            print("Erro no detector de Liquidity Vacuum:", e)
            return None

    def detectMarketMakerTrap(self):
        """
        Detecta armadilha de market maker (fake breakout + reversão).
        Retorna BUY, SELL ou None.
        """

        try:

            closes = self.stock_data["close_price"]
            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 20:
                return None

            current_close = closes.iloc[-1]
            previous_close = closes.iloc[-2]

            recent_high = highs.iloc[-20:-1].max()
            recent_low = lows.iloc[-20:-1].min()

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            # trap de compra (fake breakout para baixo)
            if previous_close < recent_low and current_close > recent_low and current_volume > avg_volume * 1.5:

                print("🪤 Market Maker Trap detectada (reversão para cima)")
                return "BUY"

            # trap de venda (fake breakout para cima)
            if previous_close > recent_high and current_close < recent_high and current_volume > avg_volume * 1.5:

                print("🪤 Market Maker Trap detectada (reversão para baixo)")
                return "SELL"

            return None

        except Exception as e:

            print("Erro no detector de Market Maker Trap:", e)
            return None    
        
    def calculatePositionSize(self, signal, sweep_signal, trap_signal, grab_signal, whale_signal, volume_spike, compression_signal):
        """
        Define o tamanho da posição baseado na força do setup.
        """

        base_capital = self.capital

        if trap_signal:
            print("💰 Setup forte: Market Maker Trap")
            return base_capital * 1.0

        elif sweep_signal:
            print("💰 Setup forte: Liquidity Sweep")
            return base_capital * 0.9
        
        elif grab_signal:
            print("💰 Setup forte: Liquidity Grab")
            return base_capital * 0.85

        elif whale_signal and volume_spike:
            print("💰 Setup institucional detectado")
            return base_capital * 0.8

        elif compression_signal:
            print("💰 Breakout após compressão")
            return base_capital * 0.7

        else:
            print("💰 Setup padrão")
            return base_capital * 0.4
        
    def detectVolatilityCompression(self):
        """
        Detecta compressão de volatilidade (Bollinger squeeze simplificado).
        Geralmente precede movimentos fortes.
        """

        try:

            closes = self.stock_data["close_price"]

            if len(closes) < 20:
                return False

            std = closes.iloc[-20:].std()
            mean = closes.iloc[-20:].mean()

            if mean == 0:
                return False

            bollinger_width = (std * 2) / mean

            print(f"📉 Compressão volatilidade: {bollinger_width:.4f}")

            if bollinger_width < 0.004:
                print("📦 Compressão de volatilidade detectada")
                return True

            return False

        except Exception as e:

            print("Erro no detector de compressão:", e)

            return False
    
    def getSafeOrderBook(self):

        depth = self.getCachedOrderBook()

        if not depth:
            return [], []

        bids = depth.get("bids", [])
        asks = depth.get("asks", [])

        if not bids or not asks:
            return [], []

        return bids, asks
    
    def detectSilentAccumulation(self):

        try:

            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]
            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]

            if len(closes) < 30:
                return False

            # -------------------------
            # 1️⃣ Compressão de preço

            price_range = (
                closes.iloc[-20:].max() - closes.iloc[-20:].min()
            ) / closes.iloc[-20:].min()

            compression = price_range < 0.015

            # -------------------------
            # 2️⃣ Crescimento progressivo de volume

            avg_volume = volumes.iloc[-20:-5].mean()
            recent_volume = volumes.iloc[-5:].mean()

            volume_growth = recent_volume > avg_volume * 1.5

            # -------------------------
            # 3️⃣ Pressão de compra

            buy_pressure = closes.iloc[-1] > closes.iloc[-2]

            # -------------------------
            # 4️⃣ ATR baixo (mercado comprimido)

            atr = (highs - lows).rolling(14).mean().iloc[-1]
            atr_pct = atr / closes.iloc[-1]

            low_volatility = atr_pct < 0.004

            # -------------------------
            # DECISÃO FINAL

            if compression and volume_growth and buy_pressure and low_volatility:

                print("🏦 ACUMULAÇÃO INSTITUCIONAL FORTE DETECTADA")

                print(f"Range: {price_range*100:.2f}%")
                print(f"Volume growth: {recent_volume/avg_volume:.2f}x")

                return True

            return False

        except Exception as e:

            print("Erro detector acumulação:", e)

            return False
        
    def detectIcebergOrders(self):

        try:

            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 30:
                return False

            # Range de preço curto
            price_range = (
                closes.iloc[-15:].max() - closes.iloc[-15:].min()
            ) / closes.iloc[-15:].min()

            # Volume médio
            avg_volume = volumes.iloc[-25:-5].mean()
            recent_volume = volumes.iloc[-5:].mean()

            volume_spike = recent_volume > avg_volume * 1.8

            # candles pequenos = absorção
            candle_size = abs(closes.iloc[-1] - closes.iloc[-2])
            small_candle = candle_size < closes.iloc[-1] * 0.001

            if price_range < 0.01 and volume_spike and small_candle:

                print("🐋 ICEBERG ORDER DETECTADA")
                print(f"Volume spike: {recent_volume/avg_volume:.2f}x")

                return True

            return False

        except Exception as e:

            print("Erro no detector iceberg:", e)

            return False
        
    def tradeQualityFilter(self):

        try:

            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 30:
                return False

            # -------------------------
            # 1️⃣ tendência mínima

            ma20 = closes.rolling(20).mean().iloc[-1]
            ma50 = closes.rolling(50).mean().iloc[-1]

            trend_strength = abs(ma20 - ma50) / closes.iloc[-1]

            # -------------------------
            # 2️⃣ volatilidade mínima

            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]

            atr = (highs - lows).rolling(14).mean().iloc[-1]
            atr_pct = atr / closes.iloc[-1]

            # -------------------------
            # 3️⃣ volume mínimo

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            volume_ok = current_volume > avg_volume * 0.8

            # -------------------------
            # DECISÃO

            if trend_strength > 0.0015 and atr_pct > 0.002 and volume_ok:

                print("✅ Trade passou no filtro de qualidade")

                return True

            print("⛔ Trade bloqueado pelo filtro de qualidade")

            return False

        except Exception as e:

            print("Erro no tradeQualityFilter:", e)

            return False
    
    def btcTrendFilter(self):

        if hasattr(self, "btc_cache") and hasattr(self, "btc_cache_time") and time.time() - self.btc_cache_time < 120:
            return self.btc_cache

        def check_tf(interval):

            candles = self.getCachedKlines(
                symbol="BTCUSDT",
                interval=interval,
                limit=100
            )

            df = pd.DataFrame(candles)
            df["close"] = pd.to_numeric(df[4])

            ma20 = df["close"].rolling(20).mean().iloc[-1]
            ma50 = df["close"].rolling(50).mean().iloc[-1]

            return df["close"].iloc[-1] > ma20 or df["close"].iloc[-1] > ma50


        btc_5m = check_tf("5m")
        btc_15m = check_tf("15m")
        btc_1h = check_tf("1h")

        print("📊 BTC Trend Filter:")
        print(f" - 5m : {'ALTA' if btc_5m else 'BAIXA'}")
        print(f" - 15m: {'ALTA' if btc_15m else 'BAIXA'}")
        print(f" - 1h : {'ALTA' if btc_1h else 'BAIXA'}")

        result = not (btc_5m == False and btc_15m == False and btc_1h == False)

        self.btc_cache = result
        self.btc_cache_time = time.time()

        return result
    
    def detectLiquidityGrab(self):

        try:

            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]
            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 30:
                return None

            recent_low = lows.iloc[-2]
            previous_low = lows.iloc[-20:-2].min()

            recent_high = highs.iloc[-2]
            previous_high = highs.iloc[-20:-2].max()

            close = closes.iloc[-1]

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            # 🧲 Liquidity grab no fundo
            if recent_low < previous_low and close > previous_low and current_volume > avg_volume * 1.3:

                print("🧲 LIQUIDITY GRAB DETECTADO (reversão de alta)")
                return "BUY"

            # 🧲 Liquidity grab no topo
            if recent_high > previous_high and close < previous_high and current_volume > avg_volume * 1.3:

                print("🧲 LIQUIDITY GRAB DETECTADO (reversão de baixa)")
                return "SELL"

            return None

        except Exception as e:

            print("Erro no detector de liquidity grab:", e)

            return None
        
    def calculateTradeProbability(self, score, regime, spread, volume_spike):

        probability = min(score / 15, 1)

        if regime == "SIDEWAYS":
            probability -= 0.25

        if spread > 0.0015:
            probability -= 0.15

        if not volume_spike:
            probability -= 0.10

        probability = max(0, min(probability, 1))

        print(f"🎯 Probabilidade do trade: {probability:.2f}")

        return probability
    
    def detectInstitutionalAccumulation(self, closes, volumes, highs, lows):

        try:

            if len(closes) < 30:
                return False

            # compressão de preço
            price_range = (
                max(closes[-20:]) - min(closes[-20:])
            ) / max(min(closes[-20:]), 0.0000001)

            compression = price_range < 0.015

            # crescimento de volume
            avg_volume = sum(volumes[-25:-5]) / 20
            recent_volume = sum(volumes[-5:]) / 5

            volume_growth = recent_volume > avg_volume * 1.4

            # volatilidade
            atr = sum([h - l for h, l in zip(highs[-14:], lows[-14:])]) / 14
            atr_pct = atr / closes[-1]

            low_volatility = atr_pct < 0.004

            if compression and volume_growth and low_volatility:

                print("🏦 ACUMULAÇÃO INSTITUCIONAL DETECTADA")

                return True

            return False

        except:
            return False
    
    def saveBotState(self):
        """
        Salva o estado atual da posição para recuperar após reinício.
        """
        try:

            state = {
                "actual_trade_position": self.actual_trade_position,
                "last_buy_price": self.last_buy_price,
                "partial_tp_index": self.partial_tp_index,
                "trailing_stop_price": self.trailing_stop_price,
                "highest_price_since_entry": self.highest_price_since_entry
            }

            with open(STATE_FILE, "w") as f:
                json.dump(state, f)

        except Exception as e:
            print("Erro ao salvar estado do robô:", e)
    
    def loadBotState(self):

        try:

            if not os.path.exists(STATE_FILE):
                return

            with open(STATE_FILE) as f:
                state = json.load(f)

            self.actual_trade_position = state.get("actual_trade_position", False)
            self.last_buy_price = state.get("last_buy_price", 0)
            self.partial_tp_index = state.get("partial_tp_index", 0)
            self.trailing_stop_price = state.get("trailing_stop_price", 0)
            self.highest_price_since_entry = state.get("highest_price_since_entry", 0)

            print("♻️ Estado do robô recuperado com sucesso")

        except Exception as e:
            print("Erro ao carregar estado do robô:", e)
    
    def reconcilePositionWithWallet(self):

        try:

            close_price = self.stock_data["close_price"].iloc[-1]
            balance_value = self.last_stock_account_balance * close_price

            MIN_POSITION_VALUE = 5

            if balance_value >= MIN_POSITION_VALUE:
                self.actual_trade_position = True
            else:
                self.actual_trade_position = False

                if self.last_buy_price == 0:
                    self.last_buy_price = close_price

                    print("📊 Posição detectada na carteira")

                else:

                    self.actual_trade_position = False

        except Exception as e:

            print("Erro ao reconciliar posição:", e)
            
    def detectPumpExhaustion(self):

        try:

            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 20:
                return False

            # preço fazendo novo topo
            current_price = closes.iloc[-1]
            recent_high = closes.iloc[-10:-1].max()

            # volume atual
            current_volume = volumes.iloc[-1]

            # volume médio recente
            avg_volume = volumes.iloc[-10:-1].mean()

            # condição de exaustão
            price_breaking_high = current_price >= recent_high

            volume_falling = current_volume < avg_volume * 0.7

            if price_breaking_high and volume_falling:

                print("⚠️ EXAUSTÃO DE PUMP DETECTADA")

                print(f"Preço topo: {current_price}")
                print(f"Volume atual: {current_volume}")
                print(f"Volume médio: {avg_volume}")

                return True

            return False

        except Exception as e:

            print("Erro no detector de exaustão:", e)

            return False
        
    def detectWhaleExit(self):

        try:

            bids, asks = self.getSafeOrderBook()

            if not bids or not asks:
                return False

            # volume total próximo
            bid_volume = sum(float(b[1]) for b in bids[:10])
            ask_volume = sum(float(a[1]) for a in asks[:10])

            # maior parede
            largest_ask = max(float(a[1]) for a in asks[:10])
            largest_bid = max(float(b[1]) for b in bids[:10])

            imbalance = ask_volume / bid_volume if bid_volume > 0 else 0

            print(f"🐋 Whale Exit check:")
            print(f" - Ask volume: {ask_volume}")
            print(f" - Bid volume: {bid_volume}")
            print(f" - Imbalance: {imbalance:.2f}")

            # pressão forte de venda
            if imbalance > 1.8 and largest_ask > largest_bid * 2:

                print("🐋 POSSÍVEL SAÍDA DE BALEIAS DETECTADA")

                return True

            return False

        except Exception as e:

            print("Erro no detector de Whale Exit:", e)

            return False
        
    def detectSmartMoneyAccumulation(self):

        try:

            closes = self.stock_data["close_price"]
            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 40:
                return False

            # range do preço
            recent_range = (closes.iloc[-20:].max() - closes.iloc[-20:].min()) / closes.iloc[-20:].min()

            # crescimento de volume
            avg_volume = volumes.iloc[-30:-10].mean()
            recent_volume = volumes.iloc[-10:].mean()

            volume_growth = recent_volume > avg_volume * 1.4

            # volatilidade
            atr = (highs - lows).rolling(14).mean().iloc[-1]
            atr_pct = atr / closes.iloc[-1]

            low_volatility = atr_pct < 0.004

            # pressão compradora lenta
            higher_lows = lows.iloc[-5:].min() > lows.iloc[-15:-5].min()

            print("🏦 Smart Money Check:")
            print(f"Range: {recent_range*100:.2f}%")
            print(f"Volume growth: {recent_volume/avg_volume:.2f}x")
            print(f"ATR: {atr_pct*100:.2f}%")

            if recent_range < 0.02 and volume_growth and low_volatility and higher_lows:

                print("🏦 SMART MONEY ACCUMULATION DETECTADA")

                return True

            return False

        except Exception as e:

            print("Erro no detector Smart Money:", e)

            return False
        
    def detectLiquidityTrap(self):

        try:

            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]
            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 30:
                return None

            # níveis recentes
            recent_high = highs.iloc[-20:-1].max()
            recent_low = lows.iloc[-20:-1].min()

            current_high = highs.iloc[-1]
            current_low = lows.iloc[-1]
            current_close = closes.iloc[-1]

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            print("🪤 Liquidity Trap check")

            # -------------------------
            # Bear trap (entrada BUY)

            if current_low < recent_low and current_close > recent_low and current_volume > avg_volume * 1.3:

                print("🪤 BEAR TRAP DETECTADA")

                return "BUY"

            # -------------------------
            # Bull trap (entrada SELL)

            if current_high > recent_high and current_close < recent_high and current_volume > avg_volume * 1.3:

                print("🪤 BULL TRAP DETECTADA")

                return "SELL"

            return None

        except Exception as e:

            print("Erro no detector de Liquidity Trap:", e)

            return None
        
    def detectLiquidityManipulation(self):

        try:

            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]
            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 30:
                return None

            # níveis de liquidez
            recent_high = highs.iloc[-20:-2].max()
            recent_low = lows.iloc[-20:-2].min()

            prev_high = highs.iloc[-2]
            prev_low = lows.iloc[-2]

            current_close = closes.iloc[-1]

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            # -------------------------
            # Stop hunt abaixo do fundo

            if prev_low < recent_low and current_close > recent_low:

                if current_volume > avg_volume * 1.3:

                    print("🎯 STOP HUNT ABAIXO DO FUNDO DETECTADO")

                    return "BUY"

            # -------------------------
            # Stop hunt acima do topo

            if prev_high > recent_high and current_close < recent_high:

                if current_volume > avg_volume * 1.3:

                    print("🎯 STOP HUNT ACIMA DO TOPO DETECTADO")

                    return "SELL"

            return None

        except Exception as e:

            print("Erro no detector de manipulação:", e)

            return None    
        
    def detectVolatilityExpansion(self):

        try:

            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]
            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 30:
                return False

            # ATR atual
            atr_current = (highs - lows).rolling(14).mean().iloc[-1]

            # ATR anterior
            atr_previous = (highs - lows).rolling(14).mean().iloc[-5]

            if closes.iloc[-1] == 0:
                return False

            atr_current_pct = atr_current / closes.iloc[-1]
            atr_previous_pct = atr_previous / closes.iloc[-1]

            # volume
            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            volatility_expanding = atr_current_pct > atr_previous_pct * 1.5
            volume_support = current_volume > avg_volume * 1.2

            print("⚡ Volatility Expansion Check")
            print(f"ATR atual: {atr_current_pct*100:.3f}%")
            print(f"ATR anterior: {atr_previous_pct*100:.3f}%")

            if volatility_expanding and volume_support:

                print("⚡ EXPANSÃO DE VOLATILIDADE DETECTADA")

                return True

            return False

        except Exception as e:

            print("Erro no detector de volatilidade:", e)

            return False
    
    def detectOrderFlowImbalance(self):

        try:

            bids, asks = self.getSafeOrderBook()

            if not bids or not asks:
                return None

            bid_pressure = sum(float(b[0]) * float(b[1]) for b in bids[:20])
            ask_pressure = sum(float(a[0]) * float(a[1]) for a in asks[:20])

            if ask_pressure == 0:
                return None

            imbalance = bid_pressure / ask_pressure

            # histórico
            if not hasattr(self, "last_imbalance"):
                self.last_imbalance = imbalance

            delta = imbalance - self.last_imbalance

            self.last_imbalance = imbalance

            print(f"📊 OrderFlow: {imbalance:.2f} | Δ {delta:.2f}")

            # pressão crescente
            if imbalance > 1.5 and delta > 0.15:
                print("🟢 PRESSÃO COMPRADORA CRESCENTE")
                return "BUY"

            # pressão vendedora
            if imbalance < 0.7 and delta < -0.15:
                print("🔴 PRESSÃO VENDEDORA CRESCENTE")
                return "SELL"

            return None

        except Exception as e:

            print("Erro no OrderFlow:", e)
            return None
        
    def detectMomentumAcceleration(self):

        closes = self.stock_data["close_price"]

        if len(closes) < 10:
            return False

        r1 = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]
        r2 = (closes.iloc[-2] - closes.iloc[-3]) / closes.iloc[-3]
        acceleration = r1 - r2

        print(f"⚡ Momentum acceleration: {acceleration:.5f}")

        if acceleration > 0.001:
            print("⚡ Momentum acelerando")
            return True

        return False
    
    def resetForNewSymbol(self):

        self.last_buy_price = 0
        self.last_sell_price = 0
        self.actual_trade_position = False
        self.trailing_stop_price = 0
        self.highest_price_since_entry = 0
        
    def marketRiskFilter(self):

        if self.market_cache is not None and time.time() - self.market_cache_time < 120:
            return self.market_cache

        btc = self.getCachedKlines(
            symbol="BTCUSDT",
            interval="5m",
            limit=50
        )

        eth = self.getCachedKlines(
            symbol="ETHUSDT",
            interval="5m",
            limit=50
        )

        btc_df = pd.DataFrame(btc)
        eth_df = pd.DataFrame(eth)

        btc_df["close"] = pd.to_numeric(btc_df[4])
        eth_df["close"] = pd.to_numeric(eth_df[4])

        btc_ma = btc_df["close"].rolling(20).mean().iloc[-1]
        eth_ma = eth_df["close"].rolling(20).mean().iloc[-1]

        btc_price = btc_df["close"].iloc[-1]
        eth_price = eth_df["close"].iloc[-1]

        result = not (btc_price < btc_ma and eth_price < eth_ma)

        self.market_cache = result
        self.market_cache_time = time.time()

        return result

    def detectVolumeDelta(self):

        try:

            if hasattr(self, "trades_cache") and time.time() - self.trades_cache_time < 45:
                trades = self.trades_cache
            else:
                trades = self.client_binance.get_recent_trades(
                    symbol=self.operation_code,
                    limit=200
                )
                self.trades_cache = trades
                self.trades_cache_time = time.time()

            buy_volume = 0
            sell_volume = 0

            for t in trades:

                qty = float(t["qty"])

                if t["isBuyerMaker"]:
                    sell_volume += qty
                else:
                    buy_volume += qty

            delta = buy_volume - sell_volume

            print(f"📊 Volume Delta: {delta:.4f}")

            if delta > 0:
                return "BUY"

            if delta < 0:
                return "SELL"

            return None

        except Exception as e:

            print("Erro no volume delta:", e)
            return None
        
    def detectStopHunt(self):

        try:

            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]
            if self.stock_data is None or len(self.stock_data) < 10:
                return None
            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 40:
                return None

            # níveis de liquidez
            liquidity_high = highs.iloc[-30:-5].max()
            liquidity_low = lows.iloc[-30:-5].min()

            current_high = highs.iloc[-1]
            current_low = lows.iloc[-1]
            current_close = closes.iloc[-1]

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            print("🎯 Stop Hunt Check")

            # stop hunt de vendedores (break de topo)
            if current_high > liquidity_high and current_volume > avg_volume * 1.4:

                print("🐋 STOP HUNT ACIMA DO TOPO")

                if current_close > liquidity_high:
                    print("🚀 Continuação de alta provável")
                    return "BUY"

                else:
                    print("⚠️ Fake breakout detectado")
                    return "SELL"

            # stop hunt de compradores (break de fundo)
            if current_low < liquidity_low and current_volume > avg_volume * 1.4:

                print("🐋 STOP HUNT ABAIXO DO FUNDO")

                if current_close < liquidity_low:
                    print("🔻 Continuação de baixa provável")
                    return "SELL"

                else:
                    print("⚠️ Reversão após stop hunt")
                    return "BUY"

            return None

        except Exception as e:

            print("Erro no detector de Stop Hunt:", e)

            return None
    
    def reconnect(self):
        try:
            self.client_binance = BinanceClient(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=self.testnet
            )
            print("🔌 Reconectado à Binance")
        except Exception as e:
            print("❌ Falha ao reconectar:", e)
            
    def detectRealBreakout(self):

        try:

            closes = self.stock_data["close_price"]
            highs = self.stock_data["high_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 30:
                return None

            recent_high = highs.iloc[-20:-1].max()

            current_close = closes.iloc[-1]
            prev_close = closes.iloc[-2]

            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            breakout = current_close > recent_high * 1.001

            strong_volume = current_volume > avg_volume * 1.6

            momentum = (current_close - prev_close) / prev_close

            momentum_ok = momentum > 0.002

            if breakout and strong_volume and momentum_ok:

                print("🚀 BREAKOUT REAL CONFIRMADO")
                print(f"Momentum: {momentum*100:.2f}%")
                print(f"Volume spike: {current_volume/avg_volume:.2f}x")

                return "BUY"

            return None

        except Exception as e:

            print("Erro no detector de breakout:", e)

            return None
        
    def convert_dust_to_bnb(self):

        try:

            account = self.client_binance.get_account()

            assets = []
            dust_values = []

            for bal in account["balances"]:

                asset = bal["asset"]
                free = float(bal["free"])

                if free <= 0:
                    continue

                if asset in ["USDT", "BNB", "BTC", "ETH"]:
                    continue

                if asset.startswith("LD") or asset.startswith("BNFCR"):
                    continue

                symbol = f"{asset}USDT"

                try:

                    ticker = self.client_binance.get_symbol_ticker(symbol=symbol)

                    price = float(ticker["price"])
                    value_usdt = free * price

                    if value_usdt < 0.001:
                        continue

                    if value_usdt > 5:
                        continue

                    assets.append(asset)
                    dust_values.append(value_usdt)

                except:
                    continue

            total_dust_value = sum(dust_values)

            if total_dust_value < 1:
                return total_dust_value

            if not assets:
                print("🧹 Nenhuma poeira encontrada.")
                return total_dust_value

            assets = assets[:10]

            assets_string = ",".join(assets)

            print(f"🧹 Convertendo poeira ({total_dust_value:.2f} USDT): {assets_string}")

            self.client_binance.transfer_dust(asset=assets)

            print("🟢 Poeira convertida para BNB!")

            return total_dust_value

        except Exception as e:

            print(f"⚠️ Erro convertendo poeira: {e}")
            return 0
        
    def rebalance_profit(self, profit):

        try:

            if self.daily_profit < 20:
                return

            print(f"💰 Rebalanceando lucro: {self.daily_profit:.2f} USDT")

            btc_amount = self.daily_profit * 0.5
            bnb_amount = self.daily_profit * 0.3

            #comprar BTC          
            self.client_binance.create_order(
                symbol="BTCUSDT",
                side="BUY",
                type="MARKET",
                quoteOrderQty=btc_amount
            )
            
            #comprar BNB         
            self.client_binance.create_order(
                symbol="BNBUSDT",
                side="BUY",
                type="MARKET",
                quoteOrderQty=bnb_amount
            )
            
            print("🟢 Lucro convertido em BTC + BNB")

            #reset
            self.daily_profit = 0            

        except Exception as e:
            print("Erro no rebalance:", e)
            
    def detectVolatilityExplosionSetup(self):

        try:

            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 30:
                return False

            # compressão recente
            recent_range = (
                closes.iloc[-20:].max() - closes.iloc[-20:].min()
            ) / closes.iloc[-20:].min()

            compression = recent_range < 0.008

            # volume começando a crescer
            avg_volume = volumes.iloc[-20:-5].mean()
            recent_volume = volumes.iloc[-3:].mean()

            volume_rising = recent_volume > avg_volume * 1.4

            # pequeno movimento inicial
            momentum = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]

            if compression and volume_rising and momentum > 0:

                print("💣 POSSÍVEL EXPLOSÃO DE VOLATILIDADE")

                print(f"Range comprimido: {recent_range*100:.3f}%")
                print(f"Volume growth: {recent_volume/avg_volume:.2f}x")

                return True

            return False

        except Exception as e:

            print("Erro detector explosão:", e)

            return False
    
    def dust_manager(self):

        while True:

            try:

                if not hasattr(self, "client_binance"):
                    time.sleep(60)
                    continue

                print("🧹 Iniciando verificação de poeira...")

                total_dust_value = self.convert_dust_to_bnb()

                if total_dust_value < 1:
                    print("🧹 Poeira muito pequena. Ignorando conversão.")

            except Exception as e:
                print("⚠️ Erro dust manager:", e)

            time.sleep(86400)
            
    def fastMarketFilter(self):

        if self.stock_data is None or len(self.stock_data) < 50:
            return False

        avg_volume = self.stock_data["volume"].iloc[-20:].mean()
        close_price = self.stock_data["close_price"].iloc[-1]

        avg_quote_volume = avg_volume * close_price

        if avg_quote_volume < 8000:
            print("⚠️ Liquidez baixa.")
            return False

        if self.isLowVolatility():
            print("⚠️ Volatilidade baixa.")
            return False

        regime = self.detectMarketRegime()

        if regime == "SIDEWAYS":
            print("⚠️ Mercado lateral.")
            return False

        if not self.btcTrendFilter():
            print("⚠️ BTC em queda.")
            return False

        return True
    
    def fastMarketScanner(self):

        now = time.time()

        # usar cache se ainda estiver válido
        if now - self.scanner_cache_time < self.scanner_cache_ttl:
            return self.scanner_cache

        print("🔎 Escaneando mercado rápido...")

        tickers = self.client_binance.get_ticker()  # 24h stats de todos os pares

        ranking = []

        for t in tickers:

            symbol = t["symbol"]

            if not symbol.endswith("USDT"):
                continue

            price = float(t["lastPrice"])
            volume = float(t["quoteVolume"])
            change = float(t["priceChangePercent"])
            
            # ignorar moedas muito baratas (ruído)
            if price < 0.00001:
                continue

            # filtro de liquidez
            if volume < 5_000_000:
                continue

            score = 0

            # volume forte
            if volume > 30_000_000:
                score += 3
            elif volume > 15_000_000:
                score += 2
            elif volume > 8_000_000:
                score += 1

            # momentum diário
            if change > 4:
                score += 3
            elif change > 2:
                score += 2
            elif change > 1:
                score += 1

            # bônus para moedas com bom movimento
            if abs(change) > 5:
                score += 1           
            
            ranking.append((symbol, score, change, volume))

        ranking.sort(key=lambda x: x[1], reverse=True)

        top = ranking[:6]

        print("🔥 TOP OPORTUNIDADES:", [r[0] for r in top])

        # salvar cache
        self.scanner_cache = top
        self.scanner_cache_time = now

        return top
    
    def mediumMarketAnalysis(self):

        momentum = self.detectMomentumAcceleration()
        volume_spike = self.detectPump()
        orderflow = self.detectOrderFlowImbalance()
        compression = self.detectVolatilityCompression()

        score = 0

        if momentum:
            score += 2

        if volume_spike:
            score += 2

        if orderflow == "BUY":
            score += 2

        if compression:
            score += 1

        print(f"📊 Score intermediário: {score}")

        return score >= 3
    
    def scalePosition(self):

        try:

            if not self.actual_trade_position:
                return False

            if self.scale_level >= self.max_scale_levels:
                return False

            close_price = self.stock_data["close_price"].iloc[-1]

            profit_pct = self.getPriceChangePercentage(
                self.last_buy_price,
                close_price
            )

            trigger = self.scale_trigger_levels[self.scale_level]

            if profit_pct < trigger:
                return False

            # confirmação institucional
            momentum = self.detectMomentumAcceleration()
            whale_signal = self.detectWhalePressure()
            orderflow = self.detectOrderFlowImbalance()

            if not momentum:
                return False

            if whale_signal != "BUY":
                return False

            if orderflow != "BUY":
                return False

            print(f"🚀 SCALE {self.scale_level + 1} DETECTADO")

            # tamanho progressivo
            capital_extra = self.capital * (0.25 + self.scale_level * 0.25)

            quantity = capital_extra / close_price
            quantity = self.adjust_to_step(quantity, self.step_size)

            if quantity <= 0:
                return False

            self.buyMarketOrder(quantity=quantity)

            self.scale_level += 1

            print(f"📈 Scale executado nível {self.scale_level}")

            return True

        except Exception as e:

            print("Erro no scale position:", e)

            return False
        
    def calculateAdaptivePositionSize(
        self,
        score,
        probability,
        sweep_signal,
        trap_signal,
        whale_signal,
        volume_spike
    ):

        base_capital = self.capital * 0.25

        multiplier = 1.0

        # força do score
        if score >= 9:
            multiplier += 0.8
        elif score >= 7:
            multiplier += 0.4
        elif score >= 5:
            multiplier += 0.2

        # probabilidade da estratégia
        if probability > 0.65:
            multiplier += 0.3
        elif probability < 0.45:
            multiplier -= 0.3

        # sinais institucionais
        if whale_signal == "BUY":
            multiplier += 0.3

        if volume_spike:
            multiplier += 0.2

        if sweep_signal:
            multiplier += 0.2

        if trap_signal:
            multiplier -= 0.2

        # limite de risco
        multiplier = max(0.3, min(multiplier, 2.5))

        capital_to_use = base_capital * multiplier

        return capital_to_use
    
    def detectMomentumExpansion(self):

        try:

            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 20:
                return False

            # movimento recente
            move_short = (closes.iloc[-1] - closes.iloc[-3]) / closes.iloc[-3]

            # movimento anterior
            move_prev = (closes.iloc[-3] - closes.iloc[-6]) / closes.iloc[-6]

            # aceleração
            acceleration = move_short - move_prev

            # volume
            avg_volume = volumes.iloc[-20:].mean()
            current_volume = volumes.iloc[-1]

            volume_expansion = current_volume > avg_volume * 1.4

            print(f"⚡ Momentum Expansion: {acceleration:.5f}")

            if acceleration > 0.002 and volume_expansion:

                print("🚀 MOMENTUM EXPANSION DETECTADO")

                return True

            return False

        except Exception as e:

            print("Erro no detector de momentum expansion:", e)

            return False
        
    def getCachedKlines(self, symbol, interval, limit=100):

        key = f"{symbol}_{interval}_{limit}"

        now = time.time()

        if (
            key in self.candles_cache
            and now - self.candles_cache_time.get(key, 0) < self.candle_cache_ttl
        ):
            return self.candles_cache[key]

        candles = self.getCachedKlines(
            symbol=symbol,
            interval=interval,
            limit=limit
        )

        self.candles_cache[key] = candles
        self.candles_cache_time[key] = now

        return candles
    
    def detectVolumeDivergence(self):

        try:

            closes = self.stock_data["close_price"]
            volumes = self.stock_data["volume"]

            if len(closes) < 15:
                return False

            price_move = closes.iloc[-1] - closes.iloc[-5]
            volume_move = volumes.iloc[-1] - volumes.iloc[-5]

            print(f"📊 Divergência | price_move={price_move:.5f} volume_move={volume_move:.2f}")

            # preço sobe mas volume cai
            if price_move > 0 and volume_move < 0:
                print("⚠️ Divergência bearish detectada")
                return True

            return False

        except Exception as e:

            print("Erro detectVolumeDivergence:", e)

            return False