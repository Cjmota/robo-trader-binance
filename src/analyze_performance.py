from src.utils.performance import plot_equity_curve
from src.utils.performance import plot_trade_distribution
from src.utils.performance import plot_drawdown
from src.utils.performance import calculate_metrics


metrics = calculate_metrics()

print(metrics)

plot_equity_curve()

plot_trade_distribution()

plot_drawdown()