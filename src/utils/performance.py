import pandas as pd
import numpy as np
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(BASE_DIR, "..", "trades_log.csv")


def load_trades():

    if not os.path.exists(TRADES_FILE):
        return pd.DataFrame(columns=["time", "symbol", "profit_usdt"])

    try:
        df = pd.read_csv(TRADES_FILE)

        if "profit_usdt" not in df.columns:
            df["profit_usdt"] = 0

        return df

    except Exception:
        return pd.DataFrame(columns=["time", "symbol", "profit_usdt"])


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

    profits = df["profit_usdt"].astype(float)

    total_trades = len(profits)

    wins = profits[profits > 0]
    losses = profits[profits < 0]

    win_rate = len(wins) / total_trades if total_trades else 0

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    expectancy = profits.mean()

    # 📈 equity
    equity_curve = profits.cumsum()

    peak = equity_curve.cummax()
    drawdown = equity_curve - peak
    max_drawdown = drawdown.min()

    # 📊 sharpe realista
    returns = profits.pct_change().dropna()

    if len(returns) > 1 and returns.std() != 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
    else:
        sharpe = 0

    return {
        "total_trades": int(total_trades),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "expectancy": float(expectancy),
        "equity": float(equity_curve.iloc[-1]),
        "max_drawdown": float(max_drawdown),
        "sharpe": float(sharpe)
    }


def equity_curve():

    df = load_trades()

    if df.empty:
        return []

    return df["profit_usdt"].cumsum().tolist()


def trade_distribution():

    df = load_trades()

    if df.empty:
        return []

    return df["profit_usdt"].tolist()