import pandas as pd
import os

def calculate_metrics():

    if not os.path.exists("trades_log.csv"):
        return {
            "total_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "expectancy": 0,
            "equity": 0,
            "max_drawdown": 0
        }

    df = pd.read_csv("trades_log.csv")

    total_trades = len(df)

    wins = df[df["profit_usdt"] > 0]
    losses = df[df["profit_usdt"] < 0]

    win_rate = len(wins) / total_trades if total_trades else 0

    gross_profit = wins["profit_usdt"].sum()
    gross_loss = abs(losses["profit_usdt"].sum())

    profit_factor = gross_profit / gross_loss if gross_loss else 0

    expectancy = df["profit_usdt"].mean()

    equity = df["profit_usdt"].cumsum()

    max_drawdown = (equity - equity.cummax()).min()

    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "equity": equity.iloc[-1] if len(equity) else 0,
        "max_drawdown": max_drawdown
    }