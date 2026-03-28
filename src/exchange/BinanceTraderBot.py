from src.data.data_provider import get_klines
from src.utils.safe_api import safe_api_call
from src.utils.binance_filters import get_symbol_filters, adjust_to_step_size
from src.utils.binance_execution import validate_order
from src.utils.report import generate_report
from src.utils.trade_logger import log_trade
import pandas as pd
import datetime
import logging
import time

from src import main

logger = logging.getLogger(__name__)

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

    def buy(self, quantity, price=None):

        if price is None:
            logger.warning("⚠️ Price não informado — usando fallback")
            return

        logger.info(f"💰 Execução real: {price}")

        if self.position_open:
            logger.warning("⚠️ Já existe posição aberta")
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
                logger.info("💸 Saldo insuficiente")
                return None

        except Exception as e:
            logger.exception("Erro ao verificar saldo")
            return None

        # -----------------------------------------
        # ⏱️ PROTEÇÃO SPAM

        if time.time() - self.last_trade_time < 2:
            logger.warning("⚠️ Ordem muito rápida")
            return None

        # -----------------------------------------
        # 🔧 VALIDAÇÃO QTD

        if quantity is None:
            logger.error("❌ BUY cancelado: quantity None")
            return None

        if not isinstance(quantity, (int, float)):
            logger.error("❌ BUY cancelado: quantity inválido")
            return None

        if quantity <= 0:
            logger.error("❌ BUY cancelado: quantity <= 0")
            return None

        quantity = float(quantity)
        quantity = round(quantity, 6)

        # -----------------------------------------
        # 🔧 AJUSTE BINANCE

        quantity = self._adjust_quantity(quantity)

        if quantity <= 0:
            logger.error("❌ Quantity inválida após ajuste")
            return None
        # -----------------------------------------
        # 📈 PREÇO (ANTES DE VALIDAR)

        if not price or price <= 0:
            logger.warning("⚠️ Sem preço → cancelando BUY")
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
            logger.error(f"⚠️ Ordem inválida: {error}")
            return None

        if quantity <= 0:
            logger.warning("⚠️ Quantidade inválida")
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
                logger.warning("⚠️ Ordem não executada")
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

            logger.info(f"🚀 BUY {self.symbol} @ {price} | qty={executed_qty} | balance_used≈{executed_qty * price:.2f}")

            log_msg = f"""
            --------------------
            ORDEM ENVIADA:
            Status: {order.get('status')}
            Side: BUY
            Ativo: {self.symbol}
            Quantidade: {executed_qty}
            Preço executado: {price}
            Valor total: {order.get('cummulativeQuoteQty')}
            Type: {order.get('type')}
            Data/Hora: {datetime.datetime.now()}

            Complete_order:
            {order}
            -----------------------------------------
            """

            logging.info(log_msg)

            return order

        except Exception as e:
            logger.error("❌ Erro no BUY:", e)
            return None
        
    # -----------------------------------------
    # 🔻 SELL

    def sell(self):

        # ✅ CORREÇÃO CRÍTICA
        if not self.position_open:
            logger.debug(f"Sem posição aberta em {self.symbol}")
            return None

        try:
            price = self.get_price()

            if price is None or price <= 0:
                logger.warning("⚠️ Preço inválido no SELL")
                return None

            quantity, _, error = validate_order(
                self.client,
                self.symbol,
                self.quantity,
                price
            )

            if error:
                logger.error(f"⚠️ SELL inválido: {error}")
                return None

            if quantity <= 0:
                logger.warning("⚠️ Quantidade inválida no SELL")
                return None

            order = safe_api_call(
                self.client.create_order,
                symbol=self.symbol,
                side="SELL",
                type="MARKET",
                quantity=quantity
            )

            if order and order.get("status") not in ["FILLED", "PARTIALLY_FILLED"]:
                logger.warning("⚠️ Ordem não executada")
                return None

            # 🔥 PREÇO REAL
            exec_price = price
            fills = order.get("fills", [])
            if fills:
                exec_price = float(fills[0]["price"])

            entry = float(self.entry_price)

            profit = float((exec_price - entry) * quantity)

            log_trade(self.symbol, profit)

            logger.info(f"💰 SELL {self.symbol} @ {exec_price} | PnL: {profit:.2f}")

            # 🔥 ATUALIZA LUCRO
            self.daily_profit += profit

            trade = {
                "time": str(datetime.datetime.now()),
                "symbol": self.symbol,
                "side": "SELL",
                "entry": entry,
                "exit": exec_price,
                "profit": profit
            }

            main.add_trade(trade)

            # 📊 relatório
            if len(main.TRADE_HISTORY) % 5 == 0:
                generate_report(main.TRADE_HISTORY)

            if self.risk_manager:
                self.risk_manager.register_trade(profit)

            # 🔥 RESET POSIÇÃO
            self.position_open = False
            self.entry_price = 0
            self.quantity = 0
            self.highest_price = 0
            self.last_trade_time = time.time()

            return order

        except Exception as e:
            logger.exception(f"Erro no SELL: {e}")
            return None
    
    # -----------------------------------------
    # 📈 PRICE

    def can_trade(self, force=False):

        cooldown = self.config.get("TEMPO_ENTRE_TRADES", 60)

        if force:
            logger.warning("🚀 Ignorando cooldown (forçado)")
            return True

        if time.time() - self.last_trade_time < cooldown:
            logger.warning("⏱️ Aguardando cooldown")
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
            logger.warning("⚠️ Não pode trocar ativo com posição aberta")    
            return
        
        logger.info(f"🔄 Mudando ativo: {self.symbol} → {symbol}")        

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
            logger.warning("🚫 Spread ruim")
            return False

        # ⚠️ momentum fraco (não bloqueia mais)
        if not momentum:
            logger.warning("⚠️ Sem momentum global")

        # ⚠️ volume fraco (não bloqueia)
        if not volume_spike:
            logger.warning("⚠️ Volume fraco")

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
                logger.warning(f"⚠️ Qty menor que minQty ({min_qty})")
                return 0

            return qty

        except Exception as e:
            logger.error(f"❌ Erro ao ajustar quantidade: {e}")
            return 0

    def get_lot_size(self, symbol):
        try:
            info = self.client.get_symbol_info(symbol)

            lot = {}
            min_notional = 5  # fallback padrão Binance

            for f in info["filters"]:

                if f["filterType"] == "LOT_SIZE":
                    lot["minQty"] = float(f["minQty"])
                    lot["maxQty"] = float(f["maxQty"])
                    lot["stepSize"] = float(f["stepSize"])

                elif f["filterType"] == "MIN_NOTIONAL":
                    min_notional = float(f["minNotional"])

                elif f["filterType"] == "NOTIONAL":  # 🔥 Binance nova
                    min_notional = float(f.get("minNotional", 5))

            lot["minNotional"] = min_notional

            return lot

        except Exception as e:
            logger.error(f"❌ Erro ao obter LOT_SIZE: {e}")
            return None
    
    def clean_position(self):
        
        if not self.position_open:
            logger.debug(f"Sem posição para limpar em {self.symbol}")
            return

        logger.info(f"🧹 Limpando posição em {self.symbol}")
        self.sell()