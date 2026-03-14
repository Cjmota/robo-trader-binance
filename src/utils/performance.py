import pandas as pd
import numpy as np
import os

TRADES_FILE = "trades_log.csv"


def load_trades():

    if not os.path.exists(TRADES_FILE):
        return pd.DataFrame(columns=["time","symbol","profit_usdt"])

    return pd.read_csv(TRADES_FILE)


def calculate_metrics():

    df = load_trades()

    if df.empty:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "expectancy": 0,
            "equity": 0,
            "max_drawdown": 0,
            "sharpe": 0
        }

    profits = df["profit_usdt"]

    total_trades = len(profits)

    wins = profits[profits > 0]
    losses = profits[profits < 0]

    win_rate = len(wins) / total_trades

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    profit_factor = gross_profit / gross_loss if gross_loss else 0

    expectancy = profits.mean()

    equity_curve = profits.cumsum()

    peak = equity_curve.cummax()
    drawdown = equity_curve - peak
    max_drawdown = drawdown.min()

    returns = profits / max(abs(profits.mean()), 1e-9)

    sharpe = (
        returns.mean() / returns.std()
        if returns.std() != 0 else 0
    )

    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "equity": equity_curve.iloc[-1],
        "max_drawdown": max_drawdown,
        "sharpe": sharpe
    }


def equity_curve():

    df = load_trades()

    profits = df["profit_usdt"]

    equity = profits.cumsum()

    return equity.tolist()


def trade_distribution():

    df = load_trades()

    profits = df["profit_usdt"]

    return profits.tolist()
