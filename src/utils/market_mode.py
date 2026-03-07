from datetime import datetime

def get_market_day():
    now = datetime.utcnow()
    return now.weekday()

def is_asian_open():
    now = datetime.utcnow()
    hour = now.hour
    
    if 22 <= hour or hour <= 2:
        return True
    
    return False

def detect_low_liquidity(volume_list):

    avg_volume = sum(volume_list) / len(volume_list)
    last_volume = volume_list[-1]

    if last_volume < avg_volume * 0.6:
        return True

    return False


def detect_market_mode(volume_list):

    day = get_market_day()

    if day == 5:
        return "LOW_ACTIVITY"

    if day == 6:

        if is_asian_open():
            return "HIGH_VOLATILITY"

        return "LOW_LIQUIDITY"

    if detect_low_liquidity(volume_list):
        return "LOW_LIQUIDITY"

    return "NORMAL"