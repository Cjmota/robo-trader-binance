import os
import json
import time
from dotenv import load_dotenv

from binance.client import Client

from src.core.engine import TradingEngine
from src.core.decision import DecisionEngine
from src.strategies.StrategyRunner import StrategyRunner
from src.exchange.BinanceTraderBot import BinanceTraderBot

from src.scanner.market_scanner_pro import scan_market_pro

from src import main  # se der erro, te explico depois

# -----------------------------------------
# 🔐 ENV

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")

# -----------------------------------------
# ⚙️ CONFIG

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "app", "config.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

config = load_config()

# -----------------------------------------
# 🚀 INIT

client = Client(API_KEY, API_SECRET)

bot = BinanceTraderBot(
    symbol="BTCUSDT",  # inicial (vai trocar no scanner)
    client=client,
    config=config
)

strategy_runner = StrategyRunner()
decision_engine = DecisionEngine(config)

# -----------------------------------------
# 🧠 ENGINE

last_scan = 0
cached_symbols = []

def get_best_symbol():
    global last_scan, cached_symbols

    if time.time() - last_scan > 20:
        cached_symbols = scan_market_pro(client)
        last_scan = time.time()

    return cached_symbols[0] if cached_symbols else None

engine = TradingEngine(
    bot=bot,
    scanner=get_best_symbol,
    strategy_runner=strategy_runner,
    decision_engine=decision_engine,
    config=config
)

<<<<<<< HEAD
# -----------------------------------------
# ▶️ START
=======
    # Tempos
    bot.time_to_trade = new_config["TEMPO_ENTRE_TRADES"]
    bot.delay_after_order = new_config["DELAY_ENTRE_ORDENS"]

def safe_binance_call(func, *args, retries=3, delay=2, **kwargs):
    """
    Executa chamadas da Binance com retry automático
    """

    for attempt in range(retries):

        try:
            return func(*args, **kwargs)

        except Exception as e:

            print(f"⚠️ Binance erro: {e}")

            if attempt < retries - 1:

                sleep_time = delay * (attempt + 1)

                print(f"🔁 Tentando novamente em {sleep_time}s...")
                time.sleep(sleep_time)

            else:

                print("❌ Falha definitiva na chamada da Binance")

                return None

# 🔥 Estratégias dinâmicas vindas do dashboard
strategy_map = {
    "getVortexTradeStrategy": getVortexTradeStrategy,
    "getMovingAverageTradeStrategy": getMovingAverageTradeStrategy,
    "getRsiTradeStrategy": getRsiTradeStrategy,
    "getMovingAverageRSIVolumeStrategy": getMovingAverageRSIVolumeStrategy,
    "runEnsembleStrategy": runEnsembleStrategy
}

MAIN_STRATEGY = strategy_map[config["MAIN_STRATEGY"]]
MAIN_STRATEGY_ARGS = config.get("MAIN_STRATEGY_ARGS", {})

FALLBACK_ACTIVATED = config["FALLBACK_ACTIVATED"]
FALLBACK_STRATEGY = strategy_map[config["FALLBACK_STRATEGY"]]
FALLBACK_STRATEGY_ARGS = config.get("FALLBACK_STRATEGY_ARGS", {})

# Define o logger
# 🔥 Configuração segura de log
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOG_DIR, "trading_bot.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)    


# fmt: off
# -------------------------------------------------------------------------------------------------
# 🟢🟢🟢 CONFIGURAÇÕES - PODEM ALTERAR - INICIO 🟢🟢🟢



# Ajustes de LOSS PROTECTION
ACCEPTABLE_LOSS_PERCENTAGE = config["ACCEPTABLE_LOSS_PERCENTAGE"]# (Em base 100%) O quando o bot aceita perder de % (se for negativo, o bot só aceita lucro) 
STOP_LOSS_PERCENTAGE = config["STOP_LOSS_PERCENTAGE"]  # (Em base 100%) % Máxima de loss que ele aceita para vender à mercado independente      

# Ajustes de TAKE PROFIT (Em base 100%)                        
#TP_AT_PERCENTAGE = [2, 4, 8]       # Em [X%, Y%]                       
#TP_AMOUNT_PERCENTAGE = [50, 50, 100]   # Vende [A%, B%]

TP_AT_PERCENTAGE = config["TP_AT_PERCENTAGE"]
TP_AMOUNT_PERCENTAGE = config["TP_AMOUNT_PERCENTAGE"]

# ------------------------------------------------------------------
# ⌛ AJUSTES DE TEMPO

# Périodo do candle análisado
CANDLE_PERIOD = config["CANDLE_PERIOD"]

TEMPO_ENTRE_TRADES = config["TEMPO_ENTRE_TRADES"]            # Tempo que o bot espera para verificar o mercado (em segundos)
DELAY_ENTRE_ORDENS = config["DELAY_ENTRE_ORDENS"]           # Tempo que o bot espera depois de realizar uma ordem de compra ou venda (ajuda a diminuir trades de borda)


# ------------------------------------------------------------------
# 🪙 MOEDAS NEGOCIADAS

stocks_traded_list = []

for stock in config["stocks_traded_list"]:
    asset = StockStartModel(
        stockCode=stock["stockCode"],
        operationCode=stock["operationCode"],
        tradedQuantity=stock["capital"],
        mainStrategy=MAIN_STRATEGY,
        mainStrategyArgs=MAIN_STRATEGY_ARGS,
        fallbackStrategy=FALLBACK_STRATEGY,
        fallbackStrategyArgs=FALLBACK_STRATEGY_ARGS,
        candlePeriod=CANDLE_PERIOD,
        stopLossPercentage=STOP_LOSS_PERCENTAGE,
        tempoEntreTrades=TEMPO_ENTRE_TRADES,
        delayEntreOrdens=DELAY_ENTRE_ORDENS,
        acceptableLossPercentage=ACCEPTABLE_LOSS_PERCENTAGE,
        fallBackActivated=FALLBACK_ACTIVATED,
        takeProfitAtPercentage=TP_AT_PERCENTAGE,
        takeProfitAmountPercentage=TP_AMOUNT_PERCENTAGE,
    )
    stocks_traded_list.append(asset)


# 🔴🔴🔴 CONFIGURAÇÕES - FIM 🔴🔴🔴
# -------------------------------------------------------------------------------------------------

last_traded_symbol = None

# 🔁 LOOP PRINCIPAL
# 🔁 LOOP PRINCIPAL INTELIGENTE (UMA MOEDA POR VEZ)

thread_lock = threading.Lock()

def get_btc_dominance(client):

    try:

        btc = client.get_ticker(symbol="BTCUSDT")
        btc_volume = float(btc["quoteVolume"])

        alt_symbols = ["ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT"]

        alt_volume = 0

        for s in alt_symbols:

            try:
                t = client.get_ticker(symbol=s)
                alt_volume += float(t["quoteVolume"])
            except:
                pass

        total = btc_volume + alt_volume

        if total == 0:
            return 0

        dominance = btc_volume / total

        return dominance

    except Exception as e:

        print("Erro calculando dominância BTC:", e)
        return 0

def trader_master_loop():

    global CURRENT_TRADER, BOT_RUNNING, BINANCE_CLIENT, last_traded_symbol

    current_trader = None
    last_outside_log = False
    last_trade_logged = False
    best_candidate = None
    best_score = 0
    momentum = 0

    try:
        if BINANCE_CLIENT is None:
            BINANCE_CLIENT = Client(API_KEY, API_SECRET)
    except Exception as e:
        print("Erro conectando Binance:", e)
        time.sleep(10)
        return

    while BOT_RUNNING:

        # 🔒 Se já existe posição aberta, não escanear mercado
        if current_trader and current_trader.actual_trade_position:

            CURRENT_TRADER = current_trader
            BINANCE_CLIENT = current_trader.client_binance

            current_trader.execute()

            time.sleep(max(3, min(8, TEMPO_ENTRE_TRADES)))
            continue
        
        # 🔓 Se não há mais posição, liberar scanner
        if current_trader and not current_trader.actual_trade_position:

            print("📉 Trade encerrado. Liberando scanner.")

            current_trader = None

        try:
            if current_trader:
                reload_runtime_config(current_trader)
        except Exception as e:
            print("Erro ao recarregar config:", e)

        # limpeza memória
        if len(MARKET_MEMORY) > 200:
            MARKET_MEMORY.clear()

        # ping conexão
        try:
            BINANCE_CLIENT.ping()
        except Exception as e:
            print("🔄 Reconectando Binance...", e)
            try:
                BINANCE_CLIENT = Client(API_KEY, API_SECRET)
            except Exception as reconnect_error:
                print("❌ Falha na reconexão:", reconnect_error)
                time.sleep(10)
                continue

        # BTC dominância
        btc_dominance = get_btc_dominance(BINANCE_CLIENT)
        print(f"📊 BTC Dominance: {btc_dominance:.2f}")

        now = datetime.now(br_tz).hour

        # limite diário
        if len(TRADE_HISTORY) >= MAX_TRADES_PER_DAY:
            print("🛑 Limite diário de trades atingido.")
            time.sleep(600)
            continue

        # procurar oportunidades
        if current_trader is None:

            best_candidate = None
            best_score = 0

            symbols = scan_market_top_symbols(BINANCE_CLIENT, limit=8)

            if not symbols:
                print("⚠️ Nenhuma oportunidade encontrada.")
                time.sleep(10)
                continue

            btc_mode = get_cached_btc_mode(BINANCE_CLIENT)

            print("📊 BTC Market Mode:", btc_mode)
            print(f"📊 BTC Dominance: {btc_dominance:.2f}")

            # pegar saldo apenas uma vez
            account = safe_binance_call(BINANCE_CLIENT.get_account)

            if not account:
                continue

            balance = 0
            for asset in account["balances"]:
                if asset["asset"] == "USDT":
                    balance = float(asset["free"])
                    break

            allowed_altcoin = None

            if btc_mode == "LOW_ACTIVITY":
                for s in symbols:
                    if s != "BTCUSDT":
                        allowed_altcoin = s
                        break        

            # priorizar BTC se dominância estiver alta
            if btc_dominance > 0.60 and symbols[0] != "BTCUSDT":
                print("⚠️ Dominância BTC alta. Priorizando BTC.")
                symbols = ["BTCUSDT"] + [s for s in symbols if s != "BTCUSDT"]
                
            # agora começa a analisar símbolos
            for symbol in symbols:

                # loss recente
                if btc_mode == "LOW_ACTIVITY":

                    if symbol != "BTCUSDT" and symbol != allowed_altcoin:
                        print(f"⚠️ Mercado fraco ({btc_mode}). Limitando altcoins.")
                        continue

                now_ts = time.time()

                if symbol in symbol_cooldown and now_ts - symbol_cooldown[symbol] < COOLDOWN_SECONDS:
                    continue

                if symbol in MARKET_MEMORY:

                    wins = MARKET_MEMORY[symbol]["wins"]
                    losses = MARKET_MEMORY[symbol]["losses"]

                    # se está perdendo mais do que ganhando, ignora
                    if losses > wins * 2:
                        print(f"⚠️ {symbol} ignorado por histórico ruim")
                        continue

                stock = symbol.replace("USDT", "")

                print(f"🎯 Testando ativo: {symbol}")
                
                candles = safe_binance_call(
                    BINANCE_CLIENT.get_klines,
                    symbol=symbol,
                    interval=Client.KLINE_INTERVAL_5MINUTE,
                    limit=30
                )

                if not candles:
                    continue

                closes = [float(c[4]) for c in candles]

                # cálculo volatilidade
                recent_high = max(closes[-20:])
                recent_low = min(closes[-20:])

                # definir momentum mínimo baseado no modo de mercado
                if btc_mode == "LOW_LIQUIDITY":
                    factor = 0.03
                elif btc_mode == "SIDEWAYS":
                    factor = 0.05
                elif btc_mode == "HIGH_VOLATILITY":
                    factor = 0.08
                else:
                    factor = 0.06
                    
                volatility = (recent_high - recent_low) / max(recent_low, 1e-8)

                min_momentum = volatility * factor
                
                min_momentum = max(min_momentum, 0.0006)
                
                # cálculo de momentum
                m1 = (closes[-1] - closes[-3]) / max(closes[-3], 1e-8)
                m2 = (closes[-3] - closes[-6]) / max(closes[-6], 1e-8)

                momentum = m1
                acceleration = m1 - m2         

                recent_high = max(closes[-20:])
                recent_low = min(closes[-20:])

                explosive_move = abs(momentum) > min_momentum * 3
                
                # log
                print(f"📈 {symbol} momentum: {momentum:.5f} | min necessário: {min_momentum}")

                # direção do movimento
                if momentum > min_momentum:
                    direction = "UP"
                elif momentum < -min_momentum:
                    direction = "DOWN"
                else:
                    print("⚠️ Momentum fraco, ignorando")
                    continue

                # filtro
                if abs(momentum) < min_momentum and not explosive_move:
                    print(f"⚠️ Momentum fraco ({momentum:.5f} < {min_momentum})")
                    continue
                
                try:

                    max_position = balance * config["RISK"]["MAX_POSITION_PERCENT"]

                    capital_config = next(
                        (s["capital"] for s in config["stocks_traded_list"]
                         if s["operationCode"] == symbol),
                        None
                    )

                    if capital_config is None:
                        continue

                    capital = min(capital_config, max_position)

                    temp_trader = BinanceTraderBot(
                        stock_code=stock,
                        operation_code=symbol,
                        traded_quantity=capital,
                        traded_percentage=100,
                        candle_period=CANDLE_PERIOD,
                        api_key=API_KEY,
                        api_secret=API_SECRET,
                        config=config,
                        testnet=TESTNET,
                        time_to_trade=TEMPO_ENTRE_TRADES,
                        delay_after_order=DELAY_ENTRE_ORDENS,
                        acceptable_loss_percentage=ACCEPTABLE_LOSS_PERCENTAGE,
                        stop_loss_percentage=STOP_LOSS_PERCENTAGE,
                        fallback_activated=FALLBACK_ACTIVATED,
                        take_profit_at_percentage=TP_AT_PERCENTAGE,
                        take_profit_amount_percentage=TP_AMOUNT_PERCENTAGE,
                        main_strategy=MAIN_STRATEGY,
                        main_strategy_args=MAIN_STRATEGY_ARGS,
                        fallback_strategy=FALLBACK_STRATEGY,
                        fallback_strategy_args=FALLBACK_STRATEGY_ARGS,
                    )
                    temp_trader.setStepSizeAndTickSize()

                    if not temp_trader.updateAllData():
                        continue

                    decision_str = temp_trader.getFinalDecisionStrategy()

                    print(f"🔎 Decisão da estratégia: {decision_str}")
                    
                    explosive_move = abs(momentum) > min_momentum * 3

                    if decision_str in ["BUY", "SELL"] or explosive_move or momentum > min_momentum * 2:

                        if explosive_move and decision_str != "BUY":
                            print(f"💥 Movimento explosivo detectado em {symbol}")

                        if decision_str is None:
                            decision_str = "BUY"

                        score = abs(momentum) * 2 + abs(acceleration) + volatility

                        if score > best_score:
                            best_candidate = temp_trader
                            best_score = score
                            print(f"🏆 Novo candidato: {symbol} | score {score:.6f} | decisão {decision_str}")   

                except Exception as e:
                    print(f"Erro ao analisar {symbol}: {e}")
                    
            
            if best_candidate is None:
                print("⚠️ Nenhum ativo com momentum suficiente.")

            if best_candidate:

                with thread_lock:

                    if current_trader is None:

                        print(f"🚀 Melhor oportunidade encontrada: {best_candidate.operation_code}")

                        current_trader = best_candidate
                        symbol_cooldown[best_candidate.operation_code] = time.time()
                        last_traded_symbol = best_candidate.operation_code


        # executar trader
        if current_trader:

            with thread_lock:

                CURRENT_TRADER = current_trader
                BINANCE_CLIENT = current_trader.client_binance

                current_trader.execute()

            if not current_trader.actual_trade_position:

                print("📉 Operação finalizada")

                if last_traded_symbol:
                    symbol_cooldown[last_traded_symbol] = time.time()

                entry = getattr(current_trader, "last_buy_price", 0)
                exit_price = getattr(current_trader, "last_sell_price", 0)
                qty = getattr(current_trader, "last_stock_account_balance", 0)

                profit = 0
                if entry and exit_price and qty:
                    profit = (exit_price - entry) * qty

                last_trade_logged = True

                TRADE_HISTORY.append({
                    "time": datetime.now(br_tz).strftime("%H:%M:%S"),
                    "symbol": current_trader.operation_code,
                    "side": "SELL",
                    "entry": round(entry, 2),
                    "exit": round(exit_price, 2),
                    "profit": round(profit, 4)
                })

                with open("trades_log.csv","a",newline="") as f:

                    writer = csv.writer(f)

                    writer.writerow([
                        datetime.now().isoformat(),
                        current_trader.operation_code,
                        profit
                    ])
                
                update_market_memory(current_trader.operation_code, profit)
                
                sleep_time = max(3, min(8, TEMPO_ENTRE_TRADES))
                time.sleep(sleep_time)

                current_trader = None
                last_traded_symbol = None 

                time.sleep(10)

        time.sleep(max(3, min(8, TEMPO_ENTRE_TRADES)))

    print("🛑 Loop do robô finalizado.")
>>>>>>> f39b86f (fix railway python path)

def safe_trader_master_loop():

    print("🔥 BOT INICIADO PELO DASHBOARD")

    try:
        engine.start()

    except Exception as e:
        print("❌ ERRO NO BOT:", e)