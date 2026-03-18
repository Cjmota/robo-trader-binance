import numpy as np

class MarketConditionDetector:

    def detect(self, df):

        if df is None or len(df) < 50:
            return "UNKNOWN"

        closes = df["close_price"]

        # 📈 tendência (inclinação)
        slope = np.polyfit(range(len(closes)), closes, 1)[0]

        # 📊 volatilidade
        volatility = closes.pct_change().std()

        # 📉 range
        price_range = (closes.max() - closes.min()) / closes.mean()

        # -----------------------------------------
        # 🔥 REGRAS

        if abs(slope) > 0.001 and volatility > 0.01:
            return "TREND"

        if volatility < 0.005:
            return "SIDEWAYS"

        if volatility > 0.03:
            return "VOLATILE"

        return "NORMAL"