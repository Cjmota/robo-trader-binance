import pandas as pd
import numpy as np
from src.indicators.vortex import vortex  # Importa a função vortex do arquivo vortex.py
# Variável global para o modo custom (para imprimir sinais intercalados)
last_custom_signal = None


def compute_RSI(series: pd.Series, period: int) -> pd.Series:
    """
    Calcula o RSI utilizando o método de Wilder (média exponencial) para suavização,
    com um período padrão de 14.
    """
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    
    # Cálculo da média exponencial com alpha = 1/period, conforme o método de Wilder
    avg_gain = up.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = down.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def getAdvancedTradeStrategy_v3(
    stock_data: pd.DataFrame,
    m7_period: int = 7,
    m200_period: int = 200,
    m50_period: int = 50,
    rsi_period: int = 14,
    slowK_window: int = 14,
    slow_stochastic_smoothing_window: int = 3,
    vortex_window: int = 14,
    verbose: bool = True,
    print_mode: str = "custom"   # Define o tipo de impressão: "std" ou "custom"
):
    """
    Estratégia avançada para criptomoedas, utilizando a função 'vortex'
    importada do arquivo vortex.py para calcular o Indicador Vortex.
    
    Cada indicador é calculado com o período correspondente:
      - M9: média móvel de 'm9_period' períodos.
      - M200: média móvel de 'm200_period' períodos.
      - RSI: período de 'rsi_period'.
      - Slow Stochastic: %K calculado com 'slowK_window' períodos e suavização com 'slow_stochastic_smoothing_window'.
      - Vortex: calculado com 'vortex_window' períodos.
    
    Condições para COMPRA:
      1. Fechamento > M200.
      2. RSI > 45.
      3. Slow Stochastic (SlowS) < 55.
      4. M9 crescente (M7 > M7[1]).
      5. VIP (VI+) > VIM (VI-).
      6. VIM decrescente (VIM < VIM[1]).
      7. VIP crescente (VIP > VIP[1]).
      8. Candle de alta (fechamento > abertura).
      
    Condições para VENDA:
      a. Se VIP < VIM e no período anterior VIP >= VIM.
      b. Se o Slow Stochastic do período anterior (Sst[1]) > 85.

    Retorna True para sinal de compra e False para sinal de venda.
    """
    df = stock_data.copy()
    df.sort_values("open_time", inplace=True)

    # Cálculo das Médias Móveis utilizando min_periods=1
    df["M7"]   = df["close_price"].rolling(window=m7_period, min_periods=1).mean()
    df["M200"] = df["close_price"].rolling(window=m200_period, min_periods=1).mean()
    df["M50"] = df["close_price"].rolling(window=m50_period, min_periods=1).mean()

    # Cálculo do MACD (chamado de MCAD no código) utilizando as EMAs de 12 e 26 períodos
    df["EMA12"] = df["close_price"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["close_price"].ewm(span=26, adjust=False).mean()
    df["MCAD"] = df["EMA12"] - df["EMA26"]

    # Linha de sinal do MACD: EMA de 9 períodos da linha MACD
    df["MACD_signal"] = df["MCAD"].ewm(span=9, adjust=False).mean()

    # Cálculo do histograma (barras do MACD): diferença entre a linha MACD e a linha de sinal
    df["MACD_histogram"] = df["MCAD"] - df["MACD_signal"]

    # Cálculo do RSI
    df["RSI14"] = compute_RSI(df["close_price"], rsi_period)
    
    # Cálculo do Slow Stochastic utilizando min_periods=1
    df["lowest_low"]   = df["low_price"].rolling(window=slowK_window, min_periods=slowK_window).min()
    df["highest_high"] = df["high_price"].rolling(window=slowK_window, min_periods=slowK_window).max()
    df["fast_K"] = 100 * (df["close_price"] - df["lowest_low"]) / (df["highest_high"] - df["lowest_low"])
    df["SlowS"] = df["fast_K"].rolling(window=slow_stochastic_smoothing_window, min_periods=slow_stochastic_smoothing_window).mean()

    # Cálculo do Indicador Vortex utilizando a função importada e preenchendo os NaN com backfill.
    df["VIP"] = vortex(df, window=vortex_window, positive=True).bfill()
    df["VIM"] = vortex(df, window=vortex_window, positive=False).bfill()
    
    # Verifica se há dados suficientes para comparação (pelo menos 2 linhas)
    if len(df) < 2:
        if verbose:
            print("⚠️ Dados insuficientes para execução da estratégia.")
        return None

    # Seleciona os últimos dois registros para comparação
    latest = df.iloc[-1]
    prev   = df.iloc[-2]
    prev_prev   = df.iloc[-3]

     # Condições para COMPRA
    buy_conditions1 = (
        (latest["M200"] > prev["M50"]) and
        (latest["SlowS"] > prev["SlowS"]) and
        (latest["SlowS"] < 75) and
        (latest["MCAD"] > 0) and
        (latest["MCAD"] > prev["MCAD"]) 
    )

    buy_conditions2 = (
        (latest["M200"] < prev["M50"]) and
        (latest["SlowS"] > prev["SlowS"]) and
        (latest["SlowS"] < 75) and
        (latest["MCAD"] > 0) and
        (latest["MCAD"] > prev["MCAD"]) 
 
    )


    
    # Condições para VENDA   
    sell_condition1 = (
        (latest["MACD_histogram"] < prev["MACD_histogram"])
        #(latest["close_price"] < latest["open_price"])
    )
 
    if sell_condition1:
        trade_decision = False  # Sinal de VENDA
    elif buy_conditions1 or buy_conditions2:  
        trade_decision = True   # Sinal de COMPRA
    else:
        trade_decision = None

    # Impressão dos dados (verbose)
    # Função auxiliar para impressão dos detalhes do candle
    def print_details():
        # Presume-se que o índice do DataFrame contenha a data do candle.
        data_candle = latest.name
        if isinstance(data_candle, pd.Timestamp):
            data_candle_str = data_candle.strftime("%d/%m/%Y %H:%M:%S")
        else:
            data_candle_str = str(data_candle)
            
        print("-------")
        print("📊 Estratégia: Indicadores Avançados (Vortex + Outros)")
        print(f" | Candle (index): {data_candle_str}")
        
        # Impressão do campo 'open_time' do DataFrame
        if "open_time" in df.columns:
            open_time_val = latest["open_time"]
            if isinstance(open_time_val, pd.Timestamp):
                open_time_str = open_time_val.strftime("%d/%m/%Y %H:%M:%S")
            else:
                open_time_str = str(open_time_val)
            print(f" | Open Time: {open_time_str}")
        
        print(f" | Fechamento: {latest['close_price']:.3f}")
        print(f" | M200({m200_period}): {latest['M200']:.3f}")
        print(f" | M50({m50_period}): {latest['M50']:.6f}")
        print(f" | RSI{rsi_period}: {latest['RSI14']:.3f}")
        print(f" | SlowS({slow_stochastic_smoothing_window}): {latest['SlowS']:.3f}")
        #print(f" | M9({m7_period}): {latest['M7']:.3f} (Anterior: {prev['M7']:.3f})")
        print(f" | MCAD(): {latest['MCAD']:.4f} (Anterior: {prev['MCAD']:.4f} (Anterior: {prev_prev['MCAD']:.4f})")
        print(f" | MACD Signal (9): {latest['MACD_signal']:.4f}")
        print(f" | MACD Histogram: {latest['MACD_histogram']:.4f} Anterior: {prev['MACD_histogram']:.4f}")
        print(f" | VIP(VI+) ({vortex_window}): {latest['VIP']:.4f} (Anterior: {prev['VIP']:.4f})")
        print(f" | VIM(VI-) ({vortex_window}): {latest['VIM']:.4f} (Anterior: {prev['VIM']:.4f})")
        decision_text = "Comprar" if trade_decision else "Vender" if trade_decision is False else "Nenhuma ação"
        print(f" | Decisão: {decision_text}")
        print("-------")

    # Impressão dos dados
    global last_custom_signal
    if verbose:
        if print_mode == "std":
            print_details()
        elif print_mode == "custom":
            # No modo custom, mantém a estrutura, mas exibe apenas se o sinal (compra ou venda)
            # for diferente do último impresso.
            if trade_decision is not None:
                if last_custom_signal is None or last_custom_signal != trade_decision:
                    print_details()
                    last_custom_signal = trade_decision

    # Retorne o sinal se necessário para o fluxo da estratégia
    return trade_decision
