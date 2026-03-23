import os
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()


def get_client():
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")

    if not api_key or not api_secret:
        raise Exception("API_KEY ou API_SECRET não encontrados")

    return Client(api_key, api_secret)