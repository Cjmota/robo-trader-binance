from binance.client import Client
from binance.exceptions import BinanceAPIException
import time
from requests.exceptions import ReadTimeout, ConnectionError


class BinanceClient(Client):
    def __init__(
        self,
        api_key=None,
        api_secret=None,
        requests_params=None,
        tld="com",
        base_endpoint=Client.BASE_ENDPOINT_DEFAULT,
        testnet=False,
        private_key=None,
        private_key_pass=None,
        sync=True,
        ping=True,
        verbose=False,
        sync_interval=60000,  # Intervalo de ressincronização em ms
    ):
        """
        Inicializa o cliente Binance customizado, integrando a sincronização do timestamp com o atributo `timestamp_offset`.
        """
        super().__init__(
            api_key=api_key,
            api_secret=api_secret,
            requests_params=requests_params,
            tld=tld,
            base_endpoint=base_endpoint,
            testnet=testnet,
            private_key=private_key,
            private_key_pass=private_key_pass,
        )

        # Configurações de sincronização
        self.sync = sync
        self.verbose = verbose
        self.sync_interval = sync_interval
        self.last_sync_time = 0  # Armazena o tempo da última sincronização

        if self.sync:
            self.sync_time_offset()

        # Executa o ping inicial se solicitado
        if ping:
            self.ping()

    def sync_time_offset(self, force=False):
        """
        Sincroniza o desvio de tempo (`timestamp_offset`) com base no relógio local e no servidor Binance.
        Realiza a sincronização apenas se for forçada ou se o intervalo configurado tiver passado.
        """
        current_time = int(time.time() * 1000)
        if force or (current_time - self.last_sync_time >= self.sync_interval):
            try:
                server_time = self.get_server_time()["serverTime"]
                local_time = int(time.time() * 1000)
                self.timestamp_offset = server_time - local_time
                self.last_sync_time = current_time
                if self.verbose:
                    print(f"⏰ Desvio de tempo sincronizado: {self.timestamp_offset}ms")
            except Exception as e:
                print(f"⚠️ Erro ao sincronizar o desvio de tempo: {e}")
                self.timestamp_offset = 0

    def _request(self, method, uri: str, signed: bool, force_params: bool = False, **kwargs):

        max_retries = 5

        for attempt in range(max_retries):

            try:

                # 🔒 Timestamp sync
                if signed:

                    current_time = int(time.time() * 1000)

                    if self.sync and (
                        getattr(self, "timestamp_offset", None) is None
                        or abs(self.timestamp_offset) > 1000
                    ):
                        self.sync_time_offset(force=True)

                    elif self.sync and (
                        current_time - self.last_sync_time >= self.sync_interval
                    ):
                        self.sync_time_offset()

                    kwargs.setdefault("data", {})
                    kwargs["data"]["timestamp"] = int(
                        time.time() * 1000 + self.timestamp_offset
                    )

                # ⏱️ timeout
                kwargs["timeout"] = 10

                return super()._request(method, uri, signed, force_params, **kwargs)

            # 🔁 ERRO DE TIMESTAMP
            except BinanceAPIException as e:

                if e.code == -1021:
                    print("⚠️ Timestamp inválido → sincronizando relógio...")
                    self.sync_time_offset(force=True)
                    continue  # tenta novamente

                print(f"⚠️ Binance API erro: {e}")
                return None

            # 🌐 TIMEOUT / CONEXÃO
            except (ReadTimeout, ConnectionError) as e:

                print(f"⚠️ Timeout Binance ({attempt+1}/{max_retries})")

                time.sleep(2)

                continue

            # ❌ OUTROS ERROS
            except Exception as e:

                print(f"❌ Erro inesperado: {e}")
                return None

        # 🚫 FALHOU TODAS AS TENTATIVAS
        print("❌ Falha após várias tentativas na Binance")
        return None