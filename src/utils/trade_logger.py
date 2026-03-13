import csv
import os

FILE_NAME = "trades_log.csv"

def log_trade(trade):

    file_exists = os.path.isfile(FILE_NAME)

    with open(FILE_NAME, "a", newline="") as f:

        writer = csv.DictWriter(f, fieldnames=trade.keys())

        if not file_exists:
            writer.writeheader()

        writer.writerow(trade)