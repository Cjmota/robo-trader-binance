import asyncio
from binance import AsyncClient, BinanceSocketManager
from state import STATE

async def start_socket():

    client = await AsyncClient.create()
    bm = BinanceSocketManager(client)

    ts = bm.symbol_ticker_socket("BTCUSDT")

    async with ts as stream:
        while True:
            msg = await stream.recv()
            price = float(msg['c'])

            STATE["btc_price"] = price