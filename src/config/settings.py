import json
import os

# 📁 pega o caminho base do projeto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 📁 caminho do config
CONFIG_FILE = os.path.join(BASE_DIR, "app", "config.json")


def load_config():
    try:
        print(f"📁 Carregando config de: {CONFIG_FILE}")

        with open(CONFIG_FILE, "r") as f:
            return json.load(f)

    except Exception as e:
        print(f"❌ Erro ao carregar config: {e}")
        return {}