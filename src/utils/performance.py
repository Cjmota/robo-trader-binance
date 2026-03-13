import os
import pandas as pd
import matplotlib.pyplot as plt

# -------------------------------
# Cálculo de métricas
# -------------------------------

def calculate_metrics():

    df = pd.read_csv("trades_log.csv")

    total_trades = len(df)

    wins = df[df["profit_usdt"] > 0]
    losses = df[df["profit_usdt"] < 0]

    win_rate = len(wins) / total_trades if total_trades > 0 else 0

    gross_profit = wins["profit_usdt"].sum()
    gross_loss = abs(losses["profit_usdt"].sum())

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    expectancy = df["profit_usdt"].mean()

    equity = df["profit_usdt"].cumsum()

    max_drawdown = (equity - equity.cummax()).min()

    if not os.path.exists("trades_log.csv"):
        print("⚠️ Nenhum histórico de trades ainda.")
        return {
            "total_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "expectancy": 0,
            "equity": 0,
            "max_drawdown": 0
        }

    df = pd.read_csv("trades_log.csv")
    
# -------------------------------
# Curva de Equity
# -------------------------------

def plot_equity_curve():

    df = pd.read_csv("trades_log.csv")

    equity = df["profit_usdt"].cumsum()

    plt.figure()
    plt.plot(equity)
    plt.title("Equity Curve")
    plt.xlabel("Trades")
    plt.ylabel("USDT")
    plt.grid()

    plt.show()
    
    
# -------------------------------
# Lucro por trade
# -------------------------------

def plot_trade_distribution():

    df = pd.read_csv("trades_log.csv")

    plt.figure()

    plt.bar(range(len(df)), df["profit_usdt"])

    plt.title("Profit per Trade")

    plt.xlabel("Trade")

    plt.ylabel("USDT")

    plt.grid()

    plt.show()    
    
 # -------------------------------
# Drawdown
# -------------------------------       
        
        
def plot_drawdown():

    df = pd.read_csv("trades_log.csv")

    equity = df["profit_usdt"].cumsum()

    drawdown = equity - equity.cummax()

    plt.figure()

    plt.plot(drawdown)

    plt.title("Drawdown")

    plt.xlabel("Trades")

    plt.ylabel("USDT")

    plt.show()