import datetime

def generate_report(trades):

    if not trades:
        print("⚠️ Sem trades ainda")
        return

    total_profit = 0
    wins = 0
    losses = 0

    symbol_stats = {}

    for t in trades:
        profit = float(t.get("profit", 0))
        symbol = t.get("symbol")

        total_profit += profit

        if profit > 0:
            wins += 1
        else:
            losses += 1

        if symbol not in symbol_stats:
            symbol_stats[symbol] = 0

        symbol_stats[symbol] += profit

    total_trades = wins + losses
    winrate = (wins / total_trades) * 100 if total_trades > 0 else 0
    avg_profit = total_profit / total_trades if total_trades > 0 else 0

    best_symbol = max(symbol_stats, key=symbol_stats.get)
    worst_symbol = min(symbol_stats, key=symbol_stats.get)

    report_text = f"""
📊 RELATÓRIO DO BOT
-----------------------------------
💰 Lucro total: {total_profit:.2f} USDT
📈 Winrate: {winrate:.2f}%
🔁 Trades: {total_trades}
📊 Média por trade: {avg_profit:.4f} USDT
🏆 Melhor ativo: {best_symbol}
💀 Pior ativo: {worst_symbol}
-----------------------------------
"""

    print(report_text)

    # 💾 SALVAR EM ARQUIVO
    with open("logs/report.txt", "a") as f:
        f.write(f"\n{datetime.datetime.now()}\n")
        f.write(report_text)