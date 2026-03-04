import os
import sys

# garante que o Python enxergue a pasta src
sys.path.append(os.path.dirname(__file__))

from src.dashboard import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)