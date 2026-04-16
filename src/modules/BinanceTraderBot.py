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

# fmt: on


load_dotenv()
api_key = os.getenv("BINANCE_API_KEY")
secret_key = os.getenv("BINANCE_SECRET_KEY")

GLOBAL_MANAGER = {
    "max_positions": 2,
    "min_score": 3,
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

        self.client_binance = BinanceClient(
            api_key, secret_key, sync=True, sync_interval=30000, verbose=False
        )  # Inicia o client da Binance

        self.setStepSizeAndTickSize() # Seta o time_step e step_size da classe (só precisa executar 1x)
        
        self.initial_balance_position = 0
        
        self.min_trade_usdt = 10
        
        self.daily_loss = 0
        self.daily_start_balance = 0
        
        self.last_reset_day = datetime.now().date()
        
        self.portfolio = portfolio
        
        # fmt: on

    def isBought(self):
        return self.getActualTradePosition()

    # Atualiza todos os dados da conta
    # Função importante, sempre incrementar ela, em caso de novos gets
    def updateAllData(
        self,
        verbose=False,
    ):
        try:
            
            today = datetime.now().date()

            if today != self.last_reset_day:
                print("🔄 Reset diário")
                self.daily_start_balance = self.getUSDTBalance()
                self.daily_loss = 0
                self.last_reset_day = today
            
            # Dados atualizados do usuário e sua carteira
            self.account_data = self.getUpdatedAccountData()
            # Balanço atual do ativo na carteira
            self.last_stock_account_balance = self.getLastStockAccountBalance()
            # Posição atual (False = Vendido | True = Comprado)
            self.actual_trade_position = self.getActualTradePosition()
            # Atualiza dados usados nos modelos
            self.stock_data = self.getStockData()
            # Retorna uma lista com todas as ordens abertas
            self.open_orders = self.getOpenOrders()
            # Salva o último valor de compra executado com sucesso
            self.last_buy_price = self.getLastBuyPrice(verbose)
            # Salva o último valor de venda executado com sucesso
            self.last_sell_price = self.getLastSellPrice(verbose)
            # Se a posição atual for vendida, ele reseta o index do take profit
            if self.actual_trade_position == False:
                self.take_profit_index = 0
            
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

    # ------------------------------------------------------------------
    # GETS Principais

    # Busca infos atualizada da conta Binance
    def getUpdatedAccountData(self):
        return self.client_binance.get_account()  # Busca infos da conta

    # Busca o último balanço da conta, na stock escolhida.
    def getLastStockAccountBalance(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                free = float(stock["free"])
                locked = float(stock["locked"])
                return free + locked

        return 0.0

    # Checa se a posição atual é comprado ou vendido
    # Checa se a posição atual é comprado ou vendido
    
    def should_update_order(self, new_price, old_price, threshold=0.003):
        """
        Decide se deve atualizar a ordem baseado na diferença de preço
        """
        try:
            return abs(new_price - old_price) / old_price > threshold
        except Exception as e:
            print(f"Erro should_update_order: {e}")
            return True  # em dúvida, atualiza
    
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

    def getPriceChangePercentage(self, initial_price, close_price):
        if initial_price == 0:
            raise ValueError("O initial_price não pode ser zero.")

        percentual_change = ((close_price - initial_price) / initial_price) * 100
        return percentual_change

    # --------------------------------------------------------------
    # FUNÇÕES DE COMPRA

    # Compra a ação a MERCADO
    def buyMarketOrder(self, quantity=None):
        try:
            if not self.actual_trade_position:  # Se a posição for vendida

                if quantity == None:  # Se não definida, ele vende tudo na carteira
                    quantity = self.adjust_to_step(
                        self.last_stock_account_balance,
                        self.step_size,
                        as_string=True,
                    )
                else:  # Se não, ele ajusta o valor passado
                    quantity = self.adjust_to_step(
                        quantity,
                        self.step_size,
                        as_string=True,
                    )

                order_buy = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_BUY,  # Compra
                    type=ORDER_TYPE_MARKET,  # Ordem de Mercado
                    quantity=quantity,
                )

                #self.actual_trade_position = True  # Define posição como comprada
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

        # =========================
        # 🎯 DEFINIÇÃO DO PREÇO
        # =========================
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

        # =========================
        # 💰 QUANTIDADE INTELIGENTE (CORREÇÃO AQUI)
        # =========================
        min_usdt = getattr(self, "min_trade_usdt", 10)
        quantity = self.get_position_size()

        if quantity <= 0:
            print("🚫 Quantidade inválida")
            return False
        
        # =========================
        # 🚀 PREPARE ORDER (AJUSTE BINANCE)
        # =========================
        print(f"🔎 Antes prepare_order → price: {limit_price}, qty: {quantity}")

        limit_price, quantity = self.prepare_order(
            symbol,
            float(limit_price),
            float(quantity),
            side="BUY"
        )

        print(f"🔎 Depois prepare_order → price: {limit_price}, qty: {quantity}")

        if not limit_price or not quantity:
            print("🚫 Ordem inválida após prepare_order")
            return False

        # =========================
        # 🔧 FORMATAR
        # =========================
        limit_price = f"{limit_price:.8f}"
        quantity = f"{quantity:.8f}"

        # =========================
        # 📊 LOG
        # =========================
        print(f"\nEnviando ordem limitada de COMPRA para {self.operation_code}:")
        print(f" - RSI: {rsi}")
        print(f" - Quantidade: {quantity}")
        print(f" - Close Price: {close_price}")
        print(f" - Preço Limite: {limit_price}")

        # =========================
        # 📤 EXECUÇÃO
        # =========================
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
    # --------------------------------------------------------------
    # FUNÇÕES DE VENDA

    # Vende a ação a MERCADO
    def sellMarketOrder(self, quantity=None):
        try:
            if self.actual_trade_position:  # Se a posição for comprada

                if quantity == None:  # Se não definida, ele vende tudo na carteira
                    quantity = self.adjust_to_step(
                        self.last_stock_account_balance,
                        self.step_size,
                        as_string=True,
                    )
                else:  # Se não, ele ajusta o valor passado
                    quantity = self.adjust_to_step(
                        quantity,
                        self.step_size,
                        as_string=True,
                    )

                order_sell = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_SELL,  # Venda
                    type=ORDER_TYPE_MARKET,  # Ordem de Mercado
                    quantity=quantity,
                )

                #self.actual_trade_position = False  # Define posição como vendida
                createLogOrder(order_sell)  # Cria um log
                print(f"\nOrdem de VENDA a mercado enviada com sucesso:")
                # print(order_sell)
                return order_sell  # Retorna a ordem

            else:  # Se a posição já está vendida
                logging.warning("Erro ao vender: Posição já vendida.")
                print("\nErro ao vender: Posição já vendida.")
                return False

        except Exception as e:
            logging.error(f"Erro ao executar ordem de venda a mercado: {e}")
            print(f"\nErro ao executar ordem de venda a mercado: {e}")
            return False

    # Venda por um preço mínimo (Ordem Limitada)
    # [NOVA] Define o valor usando RSI e Volume Médio
    def sellLimitedOrder(
        self,
        price=None
    ):
        close_price = self.stock_data["close_price"].iloc[-1]
        volume = self.stock_data["volume"].iloc[-1]  # Volume atual do mercado
        avg_volume = self.stock_data["volume"].rolling(window=20).mean().iloc[-1]  # Média de volume
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])

        if price is None:
            if rsi > 70:  # Mercado sobrecomprado
                limit_price = close_price + (0.002 * close_price)  # Tenta vender um pouco acima
            elif volume < avg_volume:  # Volume baixo (mercado lateral)
                limit_price = close_price - (0.002 * close_price)  # Ajuste pequeno abaixo
            else:  # Volume alto (mercado volátil)
                limit_price = close_price - (0.005 * close_price)  # Ajuste maior abaixo (caso caia muito rápido)

            # Garantir que o preço limite seja maior que o mínimo aceitável
            # limit_price = max(limit_price, self.getMinimumPriceToSell())
            if limit_price < (self.last_buy_price * (1 - self.acceptable_loss_percentage)):
                print(f"\nAjuste de venda aceitável ({self.acceptable_loss_percentage*100}%):")
                print(f" - De: {limit_price:.4f}")
                # limit_price = (self.last_buy_price*(1-self.acceptable_loss_percentage))
                limit_price = self.getMinimumPriceToSell()
                print(f" - Para: {limit_price}")
        else:
            limit_price = price

        # 🚀 PREPARAÇÃO INTELIGENTE DA ORDEM

        symbol = self.operation_code

        limit_price, quantity = self.prepare_order(
            symbol,
            float(limit_price),
            float(self.last_stock_account_balance),
            side="SELL"
        )

        # 🚫 proteção
        if not limit_price or not quantity:
            print("🚫 Ordem inválida após prepare_order")
            return False

        # converter para string
        limit_price = f"{limit_price:.8f}"
        quantity = f"{quantity:.8f}"

        # Log de informações
        print(f"\nEnviando ordem limitada de VENDA para {self.operation_code}:")
        print(f" - RSI: {rsi}")
        print(f" - Quantidade: {quantity}")
        print(f" - Close Price: {close_price}")
        print(f" - Preço Limite: {limit_price}")

        # Enviar ordem limitada de VENDA
        try:
            # Por algum motivo, fazer direto por aqui resolveu um bug de mudança de preço
            # Depois vou testar novamente.
            order_sell = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_SELL,  # Venda
                type=ORDER_TYPE_LIMIT,  # Ordem Limitada
                timeInForce="GTC",  # Good 'Til Canceled (Ordem válida até ser cancelada)
                quantity=quantity,
                price=limit_price,
            )

            #self.actual_trade_position = False  # Atualiza a posição para vendida
            print(f"\nOrdem VENDA limitada enviada com sucesso:")
            # print(order_sell)
            createLogOrder(order_sell)  # Cria um log
            return order_sell  # Retorna a ordem enviada
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

    # --------------------------------------------------------------
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

        if self.isBought() and (close_price < stop_loss_price or (self.detect_dump() and not self.is_oversold())):
            print("🔴 Ativando STOP LOSS...")
            self.cancelAllOrders()
            time.sleep(2)
            self.sellMarketOrder()
            return True
        
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
                    # Define quantidade com base na posição inicial
                    
                    if self.take_profit_index >= len(self.take_profit_at_percentage):
                        return False
                    
                    if self.initial_balance_position == 0:
                        print("⚠️ Posição inicial não definida")
                        return False
                    
                    quantity_to_sell = self.initial_balance_position * (tp_amount / 100)

                    # Ajusta para step da Binance
                    quantity_to_sell = self.adjust_to_step(
                        quantity_to_sell,
                        self.step_size,
                        as_string=False
                    )

                    # Proteção
                    quantity_to_sell = min(quantity_to_sell, self.last_stock_account_balance)

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
                        
                        send_telegram(f"🎯 TAKE PROFIT {self.operation_code}\nLucro: {price_percentage_variation:.2f}%")

                        # Verifica se a ordem foi executada com sucesso
                        if order_result and "status" in order_result and order_result["status"] == "FILLED":
                            self.take_profit_index += 1
                            
                            if self.take_profit_index > 0:
                                gain = self.getPriceChangePercentage(self.last_buy_price, close_price)

                                if gain > 2:
                                    self.stop_loss_percentage = 0.002
                                elif gain > 4:
                                    self.stop_loss_percentage = 0.005
                            
                            print(f"✅ Take Profit {tp_percentage}% realizado com sucesso!")
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

    def update_trailing_stop(self):
        if not self.isBought():
            return

        current_price = self.stock_data["close_price"].iloc[-1]
        gain = self.getPriceChangePercentage(self.last_buy_price, current_price)

        if gain > 1:
            self.stop_loss_percentage = max(self.stop_loss_percentage, 0.01)

        if gain > 3:
            self.stop_loss_percentage = max(self.stop_loss_percentage, 0.02)

        if gain > 5:
            self.stop_loss_percentage = max(self.stop_loss_percentage, 0.03)    

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
    def execute(
        self,
    ):
        
       # 🔥 PRIMEIRO ATUALIZA OS DADOS
        self.updateAllData()
        
        if self.portfolio:
            count = sum(
                1 for asset in self.account_data["balances"]
                if float(asset["free"]) > 0 and asset["asset"] != "USDT"
            )
        
        # 🔥 DEPOIS VERIFICA
        if not hasattr(self, "stock_data") or self.stock_data is None or len(self.stock_data) == 0:
            print("⚠️ Dados ainda não carregados")
            return

        with lock:
            running = bot_control["running"]

        if not running:
            print("⏸ Bot pausado via painel")
            return

        if not bot_control["running"]:
            print("⏸ Bot pausado via painel")
            return
        
        if not self.can_trade():
            return
        
        print("------------------------------------------------")
        print(f'🟢 Executado {datetime.now().strftime("(%H:%M:%S) %d-%m-%Y")}\n')  # Adiciona o horário atual formatado

        # Atualiza todos os dados
        
        if "candles" not in bot_status:
            bot_status["candles"] = []

        last = self.stock_data.iloc[-1]

        candle = {
            "x": datetime.now().timestamp() * 1000,
            "o": float(last["open_price"]),
            "h": float(last["high_price"]),
            "l": float(last["low_price"]),
            "c": float(last["close_price"]),
        }

        bot_status["candles"].append(candle)
        bot_status["candles"] = bot_status["candles"][-100:]    
        
        self.update_trailing_stop()

        # ================================
        # 📊 DASHBOARD UPDATE
        # ================================

        # Atualiza horário
        bot_status["last_update"] = datetime.now().strftime("%H:%M:%S")

        # Atualiza saldo
        bot_status["balance"] = self.getUSDTBalance()

        # Atualiza posição
        bot_status["positions"][self.operation_code] = {
            "position": "LONG" if self.actual_trade_position else "OUT",
            "price": float(self.stock_data["close_price"].iloc[-1])
        }
        
        bot_status["manager"] = {
            "running": bot_control["running"],
            "max_positions": 2
        }

        # ================================
        # 📈 HISTÓRICO DE PREÇO
        # ================================

        if "price_history" not in bot_status:
            bot_status["price_history"] = []

        price = float(self.stock_data["close_price"].iloc[-1])
        bot_status["price_history"].append(price)

        # limita histórico
        bot_status["price_history"] = bot_status["price_history"][-100:]
        
        
        # ================================
        # 💰 PnL (LUCRO / PREJUÍZO)
        # ================================

        if "initial_balance" not in bot_status:
            bot_status["initial_balance"] = self.getUSDTBalance()

        current_balance = self.getUSDTBalance()
        initial_balance = bot_status["initial_balance"]

        bot_status["pnl"] = round(current_balance - initial_balance, 2)

        if initial_balance > 0:
            bot_status["pnl_percent"] = round(
                (current_balance - initial_balance) / initial_balance * 100, 2
            )
        else:
            bot_status["pnl_percent"] = 0       
        
        if not self.isBought():

            if self.portfolio:
                real_positions = self.get_real_open_positions()

                print(f"📊 Posições reais: {real_positions}/{self.portfolio.max_positions}")

                if real_positions >= self.portfolio.max_positions:
                    print("🚫 Máximo de posições global atingido")
                    return
        
        if not self.isBought():
            score = self.calculate_entry_score()
            
            vol = self.stock_data["close_price"].pct_change().rolling(20).std().iloc[-1]

            if vol < 0.002:
                print("🚫 Mercado lateral fraco - ignorando")
                return

            if vol > 0.01:
                min_score = 4
            else:
                min_score = 3

            if score < min_score:
                print("🚫 Score insuficiente")
                return
        
        # 🔥 RESTAURA ESTADO APÓS RESTART
        if self.isBought() and self.initial_balance_position == 0:
            self.initial_balance_position = self.last_stock_account_balance
            print("♻️ Restaurando posição inicial após restart")
            print(f"📦 Posição restaurada: {self.initial_balance_position:.6f} {self.stock_code}") 

        print("\n-------")
        print("Detalhes:")
        print(f' - Posição atual: {"Comprado" if self.actual_trade_position else "Vendido"}')
        print(f" - Balanço atual: {self.last_stock_account_balance:.4f} ({self.stock_code})")

        # ---------
        # Estratégias sentinelas de saída

        # Stop Loss
        # Se perder mais que o stop loss aceitável, ele sai à mercado, independente.
        # Stop Loss (somente se comprado)
        if self.isBought() and self.stopLossTrigger():
            print("\n🟢 STOP LOSS finalizado.\n")
            return
        
        if self.isBought() and self.stopLossTrigger():
            send_telegram(f"🚨 STOP LOSS {self.operation_code}")
            return

        if len(self.stock_data) < 3:
            print("⚠️ Dados insuficientes")
            return

        last_price = self.stock_data["close_price"].iloc[-1]
        prev_price = self.stock_data["close_price"].iloc[-2]

        queda = (last_price - prev_price) / prev_price

        bloquear_compra = queda < -0.02
        
        # ---------
        # Calcula a melhor estratégia para a decisão final
        decision = self.getFinalDecisionStrategy()

        if decision is None:
            print("⚠️ Estratégia inconclusiva")
            self.time_to_sleep = self.time_to_trade
            return

        self.last_trade_decision = decision
        
        if not self.isBought() and self.last_trade_decision == True:
            
            if not self.is_trend_up():
                print("🚫 Tendência maior é de baixa")
                return

            # 🚫 ANTI-DUMP (já existia)
            if bloquear_compra:
                print("🚫 Queda forte detectada - bloqueando compra")
                return

            # 🚫 ANTI-FOMO PROFISSIONAL
            current_price = self.stock_data["close_price"].iloc[-1]

            if self.is_price_stretched(self.operation_code, current_price):
                print("🚫 Compra bloqueada: preço esticado acima da média")
                return

            if self.detect_pump():
                print("🚫 Compra bloqueada: pump detectado")
                return

            if self.is_overbought():
                print("🚫 Compra bloqueada: RSI alto (topo)")
                return
        
        if not self.isBought() and self.last_trade_decision == True:
            volume = self.stock_data["volume"].iloc[-1]
            avg_volume = self.stock_data["volume"].rolling(20).mean().iloc[-1]

            if volume < avg_volume:
                print("🚫 Volume fraco - evitando entrada")
                return


        # Take Profit
        if self.isBought() and self.last_stock_account_balance > 0:
            tp_executed = self.takeProfitTrigger()

            if tp_executed:
                print("\n🟢 TAKE PROFIT finalizado.\n")
                self.time_to_sleep = self.delay_after_order
                return

        # ---------
        # Verifica ordens anteriores abertas
        if self.last_trade_decision == True:  # Se a decisão for COMPRA
            # Existem ordens de compra abertas?
            if self.hasOpenBuyOrder():  # Sim e salva possíveis quantidades executadas incompletas.
                self.cancelAllOrders()  # Cancela todas ordens
                time.sleep(2)

        if self.last_trade_decision == False:  # Se a decisão for VENDA
            # Existem ordens de venda abertas?
            if self.hasOpenSellOrder():
                order = self.open_orders[0]
                old_price = float(order["price"])

                # 🔧 calcular preço novo (igual ao sellLimitedOrder)
                close_price = self.stock_data["close_price"].iloc[-1]
                volume = self.stock_data["volume"].iloc[-1]
                avg_volume = self.stock_data["volume"].rolling(window=20).mean().iloc[-1]
                rsi = Indicators.getRSI(series=self.stock_data["close_price"])

                if rsi > 70:
                    limit_price = close_price + (0.002 * close_price)
                elif volume < avg_volume:
                    limit_price = close_price - (0.002 * close_price)
                else:
                    limit_price = close_price - (0.005 * close_price)

                # 🔥 usa o mesmo ajuste da Binance (correto)
                limit_price_adj, _ = self.prepare_order(
                    self.operation_code,
                    float(limit_price),
                    float(self.last_stock_account_balance),
                    side="SELL"
                )

                if not limit_price_adj:
                    return

                # 🔍 comparação REAL
                if not self.should_update_order(limit_price_adj, old_price):
                    print("🟡 Ordem ainda válida, não atualizar")
                    return

                limit_price = limit_price_adj

                print("🔄 Atualizando ordem (preço mudou)")
                self.cancelAllOrders()
                time.sleep(2)
        # ---------
        print("\n--------------")
        print(
            f'🔎 Decisão Final: {"Comprar" if self.last_trade_decision == True else "Vender" if self.last_trade_decision == False else "Inconclusiva"}'
        )

        if not self.isBought():
            score = self.get_market_score()

            if score < GLOBAL_MANAGER["min_score"]:
                print("🚫 Score global baixo - ignorando ativo")
                return

        # ---------
        # Se a posição for vendida (false) e a decisão for de compra (true), compra o ativo
        # Se a posição for comprada (true) e a decisão for de venda (false), vende o ativo
        if not self.isBought() and self.last_trade_decision == True:
            print("🏁 Ação final: Comprar")
            print("--------------")
            print(f"\nCarteira em {self.stock_code} [ANTES]:")
            self.printStock()
            order = self.buyLimitedOrder()

            if not order:
                print("❌ Ordem de compra falhou")
                return

            time.sleep(2)
            self.updateAllData()
            
            bot_status["balance"] = self.getUSDTBalance()

            if self.isBought():
                self.initial_balance_position = self.last_stock_account_balance
                print("✅ Compra confirmada")
                price = self.stock_data["close_price"].iloc[-1]

                send_telegram(f"🟢 COMPRA {self.operation_code}\nPreço: {price}")
                
                if self.portfolio:                    
                    current, maxp = self.portfolio.get_status()
                    print(f"📊 Posições abertas: {current}/{maxp}")
            else:
                print("⚠️ Ordem não executada ainda")
            print(f"Carteira em {self.stock_code} [DEPOIS]:")
            self.printStock()
            self.time_to_sleep = self.delay_after_order

        elif self.isBought() and self.last_trade_decision == False:
            
            
            # 🚫 PROTEÇÃO CONTRA DUMP
            if self.detect_dump() and self.is_oversold() and not self.is_trend_up():
                print("🛑 Venda bloqueada: possível fundo (dump + RSI baixo)")
                return
            
            if 'limit_price' not in locals():
                limit_price = None
            
            
            print("🏁 Ação final: Vender")
            print("--------------")
            print(f"\nCarteira em {self.stock_code} [ANTES]:")
            self.printStock()
            self.sellLimitedOrder(price=limit_price)
            time.sleep(2)
            self.updateAllData()
            print(f"\nCarteira em {self.stock_code} [DEPOIS]:")
            self.printStock()
            self.time_to_sleep = self.delay_after_order
            
            # depois do updateAllData()

            if not self.isBought():
                print("📉 Venda confirmada")

                if self.portfolio:
                    
                    current, maxp = self.portfolio.get_status()
                    print(f"📊 Posições abertas: {current}/{maxp}")

        else:
            print(f'🏁 Ação final: Manter posição ({"Comprado" if self.actual_trade_position else "Vendido"})')
            print("--------------")
            vol = self.stock_data["close_price"].pct_change().rolling(10).std().iloc[-1]

            if vol > 0.01:
                self.time_to_sleep = 60  # mercado agitado
            else:
                self.time_to_sleep = self.time_to_trade
            
        print("------------------------------------------------")

    # ================================
    # 📊 CACHE DE FILTROS (PROFISSIONAL)
    # ================================
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

            # =========================
            # 📊 FILTROS
            # =========================
            tick_size = float(filters['PRICE_FILTER']['tickSize'])
            step_size = float(filters['LOT_SIZE']['stepSize'])
            min_qty = float(filters['LOT_SIZE']['minQty'])

            # NOTIONAL pode variar
            if 'MIN_NOTIONAL' in filters:
                min_notional = float(filters['MIN_NOTIONAL']['minNotional'])
            elif 'NOTIONAL' in filters:
                min_notional = float(filters['NOTIONAL']['minNotional'])
            else:
                min_notional = 5.0

            # =========================
            # 🔧 AJUSTE DE PREÇO
            # =========================
            price = math.floor(price / tick_size) * tick_size
            price = float(f"{price:.8f}")

            # =========================
            # 🔧 AJUSTE DE QUANTIDADE
            # =========================
            quantity = math.floor(quantity / step_size) * step_size

            if quantity < min_qty:
                quantity = min_qty

            # =========================
            # 🔥 AJUSTE DE NOTIONAL
            # =========================
            notional = price * quantity

            if notional < min_notional:
                print(f"⚠️ NOTIONAL baixo: {notional:.2f} < {min_notional}")

                quantity = min_notional / price

                # reajusta no step
                quantity = math.floor(quantity / step_size) * step_size

                print(f"🔧 Nova quantidade ajustada: {quantity}")

            # =========================
            # 🔒 PROTEÇÃO FINAL
            # =========================
            notional = price * quantity

            if notional < min_notional:
                print(f"🚫 Ordem abortada: NOTIONAL final ainda inválido ({notional:.2f})")
                return None, None

            # =========================
            # 📊 LOG PROFISSIONAL
            # =========================
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
        """
        Detecta dump recente baseado em queda acumulada
        """
        try:
            prices = self.stock_data["close_price"]

            if len(prices) < candles + 1:
                return False

            recent = prices.iloc[-candles:]
            prev = prices.iloc[-candles - 1]

            #drop = (recent.iloc[-1] - prev) / prev
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
        """
        Evita comprar quando preço está muito acima da média
        (versão dinâmica baseada em volatilidade)
        """
        try:
            ma50 = self.stock_data["close_price"].rolling(window=50).mean().iloc[-1]

            if ma50 == 0:
                return False

            # 📊 VOLATILIDADE DO MERCADO
            vol = self.stock_data["close_price"].pct_change().rolling(20).std().iloc[-1]

            # 🔥 THRESHOLD DINÂMICO
            if threshold is None:
                #threshold = 0.02 if vol < 0.01 else 0.04
                #threshold = max(0.02, vol * 3)
                threshold = min(max(0.02, vol * 3), 0.08)

            distance = (price - ma50) / ma50

            print(f"📏 Distância da MA50: {distance*100:.2f}% | Threshold: {threshold*100:.2f}%")

            return distance > threshold

        except Exception as e:
            print(f"Erro is_price_stretched: {e}")
            return False
    
    def detect_pump(self, candles=3, threshold=None):
        """
        Detecta alta rápida (pump) de forma dinâmica baseada na volatilidade
        """
        try:
            prices = self.stock_data["close_price"]

            if len(prices) < candles + 1:
                return False

            start = prices.iloc[-candles - 1]
            end = prices.iloc[-1]

            change = (end - start) / start

            # 📊 VOLATILIDADE
            vol = self.stock_data["close_price"].pct_change().rolling(20).std().iloc[-1]

            # 🔥 THRESHOLD DINÂMICO
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
        score = 0

        rsi = Indicators.getRSI(series=self.stock_data["close_price"])
        ma50 = self.stock_data["close_price"].rolling(50).mean().iloc[-1]
        price = self.stock_data["close_price"].iloc[-1]

        # 🔥 LOG DETALHADO (AQUI!)
        print(f"📊 RSI: {rsi:.2f}")
        print(f"📊 Preço atual: {price:.4f}")
        print(f"📊 MA50: {ma50:.4f}")
        print(f"📊 Distância da média: {((price - ma50)/ma50)*100:.2f}%")
        print(f"📊 Candle -1: {self.stock_data['close_price'].iloc[-1]:.4f}")
        print(f"📊 Candle -3: {self.stock_data['close_price'].iloc[-3]:.4f}")

        # RSI
        if rsi < 30:
            score += 2
        elif rsi < 40:
            score += 1

        # Preço abaixo da média
        if price < ma50:
            score += 2

        # Tendência curta
        if price > self.stock_data["close_price"].iloc[-3]:
            score += 1

        print(f"🧠 Entry Score final: {score}")

        return score
    
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

        return quantity
    
    def is_trend_up(self):
        ma50 = self.stock_data["close_price"].rolling(50).mean().iloc[-1]
        ma200 = self.stock_data["close_price"].rolling(200).mean().iloc[-1]

        return ma50 > ma200
    
    def can_trade(self):
        if self.daily_loss > 0.05:  # 5% perda diária
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

        rsi = Indicators.getRSI(series=self.stock_data["close_price"])
        price = self.stock_data["close_price"].iloc[-1]
        ma50 = self.stock_data["close_price"].rolling(50).mean().iloc[-1]

        if rsi < 40:
            score += 2

        if price > ma50:
            score += 2

        if self.is_trend_up():
            score += 2

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

                # tenta pegar preço do ativo
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