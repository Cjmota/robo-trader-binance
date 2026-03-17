class BinanceTraderBotV2:

    # ==============================
    # 🚀 EXECUTE
    # ==============================
    def execute(self):

        try:

            print("\n🚀 Novo ciclo V2\n")

            symbol = self.selectBestSymbol()

            if not symbol:
                print("⚠️ Nenhum ativo")
                return

            self.operation_code = symbol

            if not self.updateAllData():
                return

            # 📊 se já está posicionado → gerenciar
            if self.actual_trade_position:
                self.managePosition()
                return

            # 📊 score
            score = self.calculateEntryScore()

            print(f"📊 Score: {score:.2f}")

            decision = self.decideEntry(score)

            if not decision:
                return

            self.executeEntry(decision)

        except Exception as e:
            print(f"❌ Erro: {e}")

    # ==============================
    # 🔄 UPDATE DADOS
    # ==============================
    def updateAllData(self, verbose=False):

        try:

            self.account_data = self.getUpdatedAccountData()
            if not self.account_data:
                return False

            self.stock_data = self.getStockData()
            if self.stock_data is None or self.stock_data.empty:
                return False

            if len(self.stock_data) < 50:
                return False

            self.last_stock_account_balance = self.getLastStockAccountBalance()

            price = self.getCachedPrice()
            if not price or price <= 0:
                return False

            position_value = self.last_stock_account_balance * price
            self.actual_trade_position = position_value >= 5

            try:
                self.open_orders = self.getOpenOrders()
            except:
                self.open_orders = []

            self.last_buy_price = self.getLastBuyPrice(verbose)
            self.last_sell_price = self.getLastSellPrice(verbose)

            if not self.actual_trade_position:
                self.take_profit_index = 0

            self.reconcilePositionWithWallet()

            return True

        except Exception as e:
            print(f"❌ updateAllData: {e}")
            return False

    # ==============================
    # 🟢 BUY
    # ==============================
    def buyMarketOrder(self, quantity=None, score=0, probability=0,
                       sweep_signal=None, trap_signal=None,
                       whale_signal=None, volume_spike=False):

        try:

            price = float(self.stock_data["close_price"].iloc[-1])

            if self.actual_trade_position:
                print("⚠️ Já comprado")
                return False

            if quantity is None:

                capital = self.calculateAdaptivePositionSize(
                    score, probability,
                    sweep_signal, trap_signal,
                    whale_signal, volume_spike
                )

                capital = min(capital, self.capital * 0.6)
                capital = max(capital, 5.25)

                quantity = capital / price

            quantity = self.adjust_to_step(quantity, self.step_size)

            if not quantity:
                return False

            if quantity * price < 5:
                return False

            if not self.hasEnoughBalanceToBuy(float(quantity), price):
                return False

            order = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=quantity,
            )

            # estado
            self.actual_trade_position = True
            self.current_symbol = self.operation_code
            self.last_trade_time = time.time()

            self.highest_price_since_entry = price
            self.trailing_stop_price = 0
            self.break_even_activated = False

            self.saveBotState()
            createLogOrder(order)

            print(f"🚀 BUY {self.operation_code} qty {quantity}")

            return order

        except Exception as e:
            print(f"❌ buyMarketOrder: {e}")
            return False

    # ==============================
    # 🔴 SELL
    # ==============================
    def sellMarketOrder(self, quantity=None):

        try:

            if not self.actual_trade_position:
                return False

            price = self.stock_data["close_price"].iloc[-1]

            if quantity is None:
                quantity = self.last_stock_account_balance

            quantity = self.adjust_to_step(quantity, self.step_size, True)

            if not quantity:
                return False

            qty = float(quantity)

            if qty * price < 5:
                return False

            order = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=quantity,
            )

            self.updateAllData()
            self.saveBotState()

            self.highest_price_since_entry = 0

            if self.last_stock_account_balance * price < 5:
                self.actual_trade_position = False
                self.current_symbol = None

            createLogOrder(order)

            print(f"🔻 SELL {self.operation_code}")

            return order

        except Exception as e:
            print(f"❌ sellMarketOrder: {e}")
            return False

    # ==============================
    # ⚙️ STEP
    # ==============================
    def adjust_to_step(self, value, step, as_string=False):

        if step <= 0:
            return None

        if value <= 0:
            return None

        step_str = f"{step:.10f}".rstrip("0")
        decimals = len(step_str.split(".")[1]) if "." in step_str else 0

        adjusted = math.floor(value / step) * step
        adjusted = round(adjusted, decimals)

        if adjusted <= 0:
            return None

        if as_string:
            return f"{adjusted:.{decimals}f}"

        return adjusted

    # ==============================
    # ⚡ MOMENTUM
    # ==============================
    def detectMomentumAcceleration(self):

        closes = self.stock_data["close_price"]

        if len(closes) < 5:
            return False

        r1 = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]
        r2 = (closes.iloc[-2] - closes.iloc[-3]) / closes.iloc[-3]

        return (r1 - r2) > 0.0004

    # ==============================
    # 🚀 PUMP
    # ==============================
    def detectPump(self):

        if len(self.stock_data) < 20:
            return False

        volume = self.stock_data["volume"].iloc[-1]
        avg_volume = self.stock_data["volume"].rolling(20).mean().iloc[-1]

        if avg_volume == 0:
            return False

        close = self.stock_data["close_price"].iloc[-1]
        prev = self.stock_data["close_price"].iloc[-2]

        if prev == 0:
            return False

        change = (close - prev) / prev

        return volume > avg_volume * 2 and change > 0.001