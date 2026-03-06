# fmt: off
import os
import time
import logging
import math
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

from src.indicators import Indicators

from src import main

# fmt: on

load_dotenv()
api_key = os.getenv("BINANCE_API_KEY")
secret_key = os.getenv("BINANCE_SECRET_KEY")


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
        testnet=False,
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
    ):

        print("------------------------------------------------")
        print("🤖 Robo Trader iniciando...")
        
        # 🔐 Credenciais da Binance
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        self.capital = traded_quantity  # valor em USDT configurado por ativo
        
        self.trailing_activation = 0.005      # ativa com +0.5% lucro
        self.trailing_stop_percent = 0.01     # trailing de 1%
        self.trailing_stop_price = 0.0
        self.highest_price_since_entry = 0.0
        
        self.sideways_counter = 0
        self.sideways_limit = 3  # nº de ciclos tolerados em lateralização
        
        self.daily_profit = 0.0
        self.daily_trades = 0
        self.last_closed_order_id = None
        self.current_day = datetime.now().date()
        
        # 🎯 Modo híbrido de realização parcial
        self.partial_take_profit_levels = [1.0, 2.0]  # %
        self.partial_take_profit_amounts = [30, 30]   # % da posição
        self.partial_tp_index = 0

        # fmt: off

        self.stock_code = stock_code  # Código princial da stock negociada (ex: 'BTC')
        self.operation_code = operation_code  # Código negociado/moeda (ex:'BTCBRL')
        self.traded_quantity = traded_quantity  # Quantidade incial que será operada
        self.traded_percentage = traded_percentage  # Porcentagem do total da carteira, que será negociada        
        self.candle_period = candle_period  # Período levado em consideração para operação (ex: 15min)        

        self.fallback_activated = fallback_activated  # Define se a estratégia de Fallback será usada (ela pode entrar comprada em mercados subindo)
        self.acceptable_loss_percentage = acceptable_loss_percentage / 100 # % Máxima que o bot aceita perder quando vender
        self.stop_loss_percentage = stop_loss_percentage / 100 # % Máxima de loss que ele aceita, em caso de não vender na ordem limitada

        self.take_profit_at_percentage = take_profit_at_percentage # Quanto de valorização para pegar lucro. (Array exemplo: [2, 5, 10])
        self.take_profit_amount_percentage = take_profit_amount_percentage # Quanto da quantidade tira de lucro. (Array exemplo: [25, 25, 40])

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

        for attempt in range(5):
            try:
                self.client_binance = BinanceClient(
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    testnet=self.testnet
                )
                break
            except ConnectionError as e:
                print(f"⚠️ Falha ao conectar Binance (tentativa {attempt+1}/5)")
                time.sleep(3)
        else:
            print("❌ Não foi possível conectar à Binance. Verifique internet/DNS.")
            raise
        
        # Break-even configurável por ativo
        self.break_even_map = {
            "BTC": 1.2 / 100,
            "SOL": 1.0 / 100,
            "BNB": 1.0 / 100,
            "ADA": 0.8 / 100,
            "XRP": 0.8 / 100,
            "SHIB": 0.6 / 100,
        }

        # fallback padrão
        self.break_even_activation = self.break_even_map.get(self.stock_code, 1.0 / 100)
                

        self.setStepSizeAndTickSize() # Seta o time_step e step_size da classe (só precisa executar 1x)

        # fmt: on

    def trailingStopTrigger(self):
        if not self.actual_trade_position:
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
        if close_price <= self.trailing_stop_price:
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

                candles = self.client_binance.get_klines(
                    symbol=self.operation_code,
                    interval=interval,
                    limit=100
                )

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

            result = trend_5m and trend_15m and trend_1h

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
            if not self.actual_trade_position:
                self.take_profit_index = 0

            return True

        except Exception as e:
            print(f"❌ Erro geral ao atualizar dados: {e}")
            return False
    
    
    # GETS Principais

    # Busca infos atualizada da conta Binance
    def getUpdatedAccountData(self):
        return self.client_binance.get_account()  # Busca infos da conta

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
        candles = self.client_binance.get_klines(
            symbol=self.operation_code,
            interval=self.candle_period,
            limit=1000,
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
            all_orders = self.client_binance.get_all_orders(
                symbol=self.operation_code,
                limit=100,
            )

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
            all_orders = self.client_binance.get_all_orders(
                symbol=self.operation_code,
                limit=100,
            )

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
    def buyMarketOrder(self, quantity=None):
        try:
            if not self.actual_trade_position:  # Se a posição for vendida

                if quantity is None:
                    close_price = self.stock_data["close_price"].iloc[-1]
                    quantity = self.capital / close_price
                else:
                    quantity = self.adjust_to_step(
                        quantity,
                        self.step_size,
                        as_string=True,
                    )

                # 🔒 Proteção contra poeira e notional mínimo
                qty_float = float(quantity)
                close_price = float(self.stock_data["close_price"].iloc[-1])
                notional_value = qty_float * close_price

                MIN_NOTIONAL = 5  # padrão Binance spot

                if qty_float < self.step_size or notional_value < MIN_NOTIONAL:
                    print("⚠️ Quantidade muito pequena para vender (poeira). Ignorando...")
                    return False

                order_buy = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_BUY,  # Compra
                    type=ORDER_TYPE_MARKET,  # Ordem de Mercado
                    quantity=quantity,
                )

                self.actual_trade_position = True  # Define posição como comprada
                createLogOrder(order_buy)  # Cria um log
                print(f"\nOrdem de COMPRA a mercado enviada com sucesso:")
                print(order_buy)
                return order_buy  # Retorna a ordem

            else:  # Se a posição já está comprada
                logging.warning("Erro ao comprar: Posição já comprada.")
                print("\nErro ao comprar: Posição já comprada.")
                return False

        except Exception as e:
            logging.error(f"Erro ao executar ordem de compra a mercado: {e}")
            print(f"\nErro ao executar ordem de compra a mercado: {e}")
            return False

    # Compra por um preço máximo (Ordem Limitada)
    # [NOVA] Define o valor usando RSI e Volume Médio
    def buyLimitedOrder(self, price=0):
        close_price = self.stock_data["close_price"].iloc[-1]
        volume = self.stock_data["volume"].iloc[-1]
        avg_volume = self.stock_data["volume"].rolling(window=20).mean().iloc[-1]
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])

        # 🔥 USAR SALDO USDT DISPONÍVEL AUTOMATICAMENTE
        try:
            account = self.client_binance.get_account()
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

        raw_quantity = usable_balance / float(close_price)

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

                remaining_balance = self.last_stock_account_balance

                # Só zera posição se vendeu praticamente tudo
                if remaining_balance * close_price < 5:
                    self.actual_trade_position = False
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

        # Ajustar preço ao tick
        limit_price = self.adjust_to_step(limit_price, self.tick_size, as_string=True)

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

    # Verifica se há alguma ordem de COMPRA aberta
    # Se a ordem foi parcialmente executada, ele salva o valor
    # executado na variável self.partial_quantity_discount, para que
    # este valor seja descontado nas execuções seguintes.
    # Se foi parcialmente executado, ela também salva o valor que foi executado
    # na variável self.last_buy_price
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

    
    
    # -------------------------------------------------------------
    # ESTRATÉGIAS DE DECISÃO

    # Função que executa estratégias implementadas e retorna a decisão final
    def getFinalDecisionStrategy(self):

        final_decision = StrategyRunner.execute(
            self,
            stock_data=self.stock_data,
            main_strategy=self.main_strategy,
            main_strategy_args=self.main_strategy_args,
            fallback_strategy=self.fallback_strategy,
            fallback_strategy_args=self.fallback_strategy_args,
        )
        
        print("📈 Rodando estratégia principal...")

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

    # --------------------------------------------------------------
    # EXECUTE

    # Função principal e a única que deve ser execuda em loop, quando o
    # robô estiver funcionando normalmente
    def execute(self):
        try:
            print("------------------------------------------------")
            print(f"🟢 Executado {datetime.now().strftime('(%H:%M:%S) %d-%m-%Y')}\n")

            # Atualiza todos os dados
            if not self.updateAllData(verbose=True):
                print("⚠️ Falha na atualização dos dados. Pulando ciclo...")
                time.sleep(2)
                return
            
            # 🔎 Detectar regime de mercado
            regime = self.detectMarketRegime()
            
            whale_signal = self.detectWhalePressure()
            sweep_signal = self.detectLiquiditySweepReversal()
            
            if self.actual_trade_position and not self.stock_data.empty:
                if self.trailingStopTrigger():
                    return

            # break even
            if self.breakEvenTrigger():
                return
            
            if self.partialTakeProfitHybrid():
                return

            # 🧹 Limpeza automática de poeira
            if self.cleanDustPosition():
                return

            self.updateDailyProfit()

            # Detecta pump
            pump_signal = self.detectPump()

            if pump_signal and not self.actual_trade_position and regime == "EXPLOSIVE":
                print("🚀 Pump confirmado em regime explosivo.")
                self.buyMarketOrder()
                return

            # Evita operar em baixa volatilidade
            if self.isLowVolatility():
                print("⏸️ Pulando trade por baixa volatilidade.")
                return
            
            if regime == "SIDEWAYS" and not sweep_signal and not whale_signal:
                print("⏸️ Mercado lateral detectado pelo regime.")
                return

            # ---------------------------------------------
            # Detector inteligente: Lateralização + Tendência
            if self.actual_trade_position:

                sideways = self.isMarketSideways()
                multi_trend_ok = self.getTrendMultiTimeframe()

                if sideways:
                    self.sideways_counter += 1
                    print(f"⚠️ Lateralização detectada ({self.sideways_counter}/{self.sideways_limit})")

                    if self.sideways_counter >= self.sideways_limit and not multi_trend_ok:
                        print("🔻 Lateralização persistente + tendência fraca detectada.")

                        if not self.stock_data.empty:
                            close_price = self.stock_data["close_price"].iloc[-1]

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
                    self.buyMarketOrder()

                return

            # ---------------------------------------------
            # ---------------------------------------------
            # EXECUTAR ESTRATÉGIA

            whale_signal = self.detectWhalePressure()

            volume_spike = self.detectPump()

            liquidity_signal = self.detectLiquidityWall()

            liquidation_signal = self.detectLiquidationMove()

            strategy_signal = self.getFinalDecisionStrategy()

            # 🔥 TODOS OS DETECTORES PRIMEIRO
            sweep_signal = self.detectLiquiditySweepReversal()

            trap_signal = self.detectMarketMakerTrap()

            compression_signal = self.detectVolatilityCompression()

            spoof_signal = self.detectSpoofing()

            multi_trend_ok = self.getTrendMultiTimeframe()
            
            # normalizar sinal
            if strategy_signal in ["Comprar", "BUY", True]:
                strategy_signal = "BUY"
            elif strategy_signal in ["Vender", "SELL", False]:
                strategy_signal = "SELL"

            print(f"📊 Estratégia: {strategy_signal}")
            print(f"💧 Liquidez: {liquidity_signal}")
            print(f"💥 Liquidação: {liquidation_signal}")

            signal = None

            # spoofing (maior prioridade)
            if spoof_signal:
                signal = spoof_signal

            # market maker trap
            elif trap_signal:
                signal = trap_signal

            # stop hunt
            elif sweep_signal:
                signal = sweep_signal

            # institucional
            elif whale_signal and volume_spike:
                signal = whale_signal

            # liquidez
            elif liquidity_signal:
                signal = liquidity_signal

            # liquidação
            elif liquidation_signal:
                signal = liquidation_signal

            # fallback estratégia
            else:
                signal = strategy_signal
        
            # ---------------------------------------------
            # COMPRA
            if signal in [True, "BUY"] and (multi_trend_ok or regime == "EXPLOSIVE"):

                # 🔎 Filtros institucionais antes da entrada
                if self.detectFakeBreakout():
                    print("⚠️ Entrada cancelada: fake breakout")
                    return

                if self.detectAbsorption():
                    print("🏦 Absorção detectada, aguardando confirmação")
                    return
                
                capital_to_use = self.calculatePositionSize(
                    signal,
                    sweep_signal,
                    trap_signal,
                    whale_signal,
                    volume_spike,
                    compression_signal
                )

                self.capital = capital_to_use

                if not self.actual_trade_position:
                    print("🚀 Entrada confirmada.")
                    self.buyLimitedOrder()

            # ---------------------------------------------
            # VENDA
            elif signal in [False, "SELL"]:

                if self.actual_trade_position:
                    print("⚠️ Saída confirmada.")
                    self.sellMarketOrder()

        except Exception as e:
            print(f"❌ Erro no ciclo do robô: {e}")
                        
    def cleanDustPosition(self):
            """
            Limpa posições residuais (dust) menores que o mínimo negociável.
            Evita loops infinitos de venda quando sobra poeira.
            """
            try:
                close_price = self.stock_data["close_price"].iloc[-1]
                notional_value = self.last_stock_account_balance * close_price

                if 0 < notional_value < 5:
                    print("\n🧹 Poeira detectada na carteira:")
                    print(f" - Quantidade: {self.last_stock_account_balance:.8f} {self.stock_code}")
                    print(f" - Valor estimado: {notional_value:.4f} USDT")
                    print("⚠️ Valor abaixo do mínimo negociável da Binance (< 5 USDT).")
                    print("🔄 Marcando posição como zerada para evitar loops de venda.\n")

                    # Marca como sem posição
                    self.actual_trade_position = False
                    self.last_stock_account_balance = 0.0
                    return True

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

            orders = self.client_binance.get_all_orders(symbol=self.operation_code, limit=50)

            # Filtra vendas executadas hoje
            filled_sells = [
                o for o in orders
                if o["side"] == "SELL" and o["status"] == "FILLED"
            ]

            for order in filled_sells:
                order_time = datetime.utcfromtimestamp(order["time"] / 1000).date()

                if order_time == today:
                    order_id = order["orderId"]

                    # Evita contar a mesma ordem duas vezes
                    if order_id != self.last_closed_order_id:
                        sell_value = float(order["cummulativeQuoteQty"])
                        buy_price = self.last_buy_price
                        qty = float(order["executedQty"])

                        if buy_price > 0:
                            cost = qty * buy_price
                            profit = sell_value - cost

                            self.daily_profit += profit
                            self.daily_trades += 1
                            self.last_closed_order_id = order_id

        except Exception as e:
            print(f"Erro ao atualizar lucro diário: {e}")
            
    def printOperationResult(self, sell_price, quantity):
        """ Mostra o lucro/prejuízo da operação atual
        """
        try:
            if self.last_buy_price == 0:
                return

            pnl_usdt = (sell_price - self.last_buy_price) * quantity
            
            main.TRADE_HISTORY.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "profit": round(pnl_usdt, 4)
            })
            
            pnl_pct = ((sell_price - self.last_buy_price) / self.last_buy_price) * 100

            print("\n💰 RESULTADO DA OPERAÇÃO")
            print(f" - Entrada : {self.last_buy_price:.4f}")
            print(f" - Saída   : {sell_price:.4f}")
            print(f" - Qtd     : {quantity:.4f}")
            print(f" - PnL     : {pnl_usdt:.4f} USDT ({pnl_pct:.2f}%)")

        except Exception as e:
            print(f"Erro ao calcular PnL: {e}")

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
        prev = self.stock_data["close_price"].iloc[-2]

        if prev == 0:
            return None

        price_change = (close - prev) / prev

        if volume > avg_volume * 2 and price_change > 0.005:

            print("🚀 POSSÍVEL PUMP DETECTADO")

            return True

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

            if recent_range < 0.005 and atr_pct < 0.002:

                print("⚠️ Mercado realmente sem volatilidade.")

                return True

            return False

        except Exception as e:

            print("Erro ao calcular volatilidade:", e)

            return False

    def detectLiquidationMove(self):

        volume = self.stock_data["volume"].iloc[-1]
        avg_volume = self.stock_data["volume"].rolling(20).mean().iloc[-1]

        close = self.stock_data["close_price"].iloc[-1]
        prev = self.stock_data["close_price"].iloc[-2]

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

            depth = self.getCachedOrderBook()
            

            bids = depth["bids"]
            asks = depth["asks"]

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

            depth = self.getCachedOrderBook()

            bids = depth["bids"]
            asks = depth["asks"]

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

            # usa cache por 5 segundos
            if self.cached_orderbook and time.time() - self.last_orderbook_check < 5:
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

            return self.cached_orderbook
        
    def detectMarketRegime(self):

        try:

            closes = self.stock_data["close_price"]
            highs = self.stock_data["high_price"]
            lows = self.stock_data["low_price"]
            volumes = self.stock_data["volume"]

            # tendência usando média
            ma20 = closes.rolling(20).mean().iloc[-1]
            ma50 = closes.rolling(50).mean().iloc[-1]

            # range
            recent_range = (closes.iloc[-20:].max() - closes.iloc[-20:].min()) / closes.iloc[-20:].min()

            # volume
            avg_volume = volumes.rolling(20).mean().iloc[-1]
            current_volume = volumes.iloc[-1]

            # ATR simplificado
            atr = (highs - lows).rolling(14).mean().iloc[-1]
            atr_pct = atr / closes.iloc[-1]

            # ----------------------------

            # mercado explosivo
            if current_volume > avg_volume * 2 and atr_pct > 0.004:
                print("🔥 REGIME: EXPLOSIVO")
                return "EXPLOSIVE"

            # mercado em tendência
            if abs(ma20 - ma50) / closes.iloc[-1] > 0.002:
                print("📈 REGIME: TREND")
                return "TREND"

            # mercado lateral
            if recent_range < 0.006:
                print("↔️ REGIME: SIDEWAYS")
                return "SIDEWAYS"

            return "NORMAL"

        except Exception as e:

            print("Erro ao detectar regime:", e)

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

            bids = depth["bids"][:10]
            asks = depth["asks"][:10]

            bid_volume = sum(float(b[1]) for b in bids)
            ask_volume = sum(float(a[1]) for a in asks)

            max_bid = max(float(b[1]) for b in bids)
            max_ask = max(float(a[1]) for a in asks)

            print(f"🕵️ Spoofing check - bid wall: {max_bid} | ask wall: {max_ask}")

            # parede muito grande comparada ao restante
            if max_bid > bid_volume * 0.6:
                print("⚠️ Possível spoofing de compra detectado")
                return "SELL"

            if max_ask > ask_volume * 0.6:
                print("⚠️ Possível spoofing de venda detectado")
                return "BUY"

            return None

        except Exception as e:

            print("Erro no detector de spoofing:", e)

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
        
    def calculatePositionSize(self, signal, sweep_signal, trap_signal, whale_signal, volume_spike, compression_signal):
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

            if bollinger_width < 0.006:
                print("📦 Compressão de volatilidade detectada")
                return True

            return False

        except Exception as e:

            print("Erro no detector de compressão:", e)

            return False