import pandas as pd
from indicators import Indicators


def getVortexTradeStrategy(stock_data: pd.DataFrame, verbose=False):
    """
    Estratégia baseada no Indicador Vortex.
    Retorna True se a posição deve estar comprada e False se deve estar vendida.
    """

    stock_data = stock_data.copy()

    # # Calcula o Indicador Vortex (VI+ e VI-)
    stock_data["VI+"] = Indicators.getVortex(stock_data, window=14, positive=True)
    stock_data["VI-"] = Indicators.getVortex(stock_data, window=14, positive=False)

    if "VI+" not in stock_data.columns or "VI-" not in stock_data.columns:
        raise ValueError("O DataFrame deve conter as colunas 'VI+' e 'VI-'. Verifique se o Vortex foi calculado.")

    vi_plus = stock_data["VI+"]
    vi_minus = stock_data["VI-"]

    # Últimos valores de VI+ e VI-
    last_vi_plus = vi_plus.iloc[-1]
    last_vi_minus = vi_minus.iloc[-1]

    # Últimos cruzamentos
    last_crossover_buy = vi_plus > vi_minus  # VI+ cruzou acima de VI- (sinal de compra)
    last_crossover_sell = vi_plus < vi_minus  # VI- cruzou acima de VI+ (sinal de venda)

    # Posição inicial
    trade_decision = None

    # Decisão de trade baseada no cruzamento
    if last_crossover_buy.iloc[-1]:
        trade_decision = True  # Compra

    elif last_crossover_sell.iloc[-1]:
        trade_decision = False  # Venda

    if verbose:
        print("-------")
        print("📊 Estratégia: Vortex")
        print(f" | VI+: {last_vi_plus:.2f}")
        print(f" | VI-: {last_vi_minus:.2f}")
        print(f' | Decisão: {"Comprar" if trade_decision else "Vender" if trade_decision is False else "Nenhuma"}')
        print("-------")

    return trade_decision
