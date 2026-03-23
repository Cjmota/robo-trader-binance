from src.scanner.market_scanner_pro import scan_market_pro
from src.utils.get_client import get_client  # ajuste se necessário

client = get_client()

ops = scan_market_pro(client)

print("SCAN RESULT:", ops)