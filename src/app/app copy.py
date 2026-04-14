from flask import Flask, request, jsonify
import logging

app = Flask(__name__)

# Configurações iniciais do bot
config = {
    "MAIN_STRATEGY": "getVortexTradeStrategy",
    "MAIN_STRATEGY_ARGS": {},
    "FALLBACK_ACTIVATED": True,
    "FALLBACK_STRATEGY": "getMovingAverageTradeStrategy",
    "FALLBACK_STRATEGY_ARGS": {},
    "ACCEPTABLE_LOSS_PERCENTAGE": 0.5,
    "STOP_LOSS_PERCENTAGE": 3.5,
    "TP_AT_PERCENTAGE": [2, 4],
    "TP_AMOUNT_PERCENTAGE": [50, 50],
    "CANDLE_PERIOD": "Client.KLINE_INTERVAL_15MINUTE",
    "TEMPO_ENTRE_TRADES": 30 * 60,
    "DELAY_ENTRE_ORDENS": 60 * 60,
    "STOCKS_TRADED": [{"stockCode": "ADA", "operationCode": "ADAUSDT", "tradedQuantity": 0}],
    "THREAD_LOCK": True,
}


# Rota para obter a configuração atual
def get_config():
    return jsonify(config)


# Rota para atualizar configurações
def update_config():
    data = request.json
    for key in data:
        if key in config:
            config[key] = data[key]
    return jsonify({"message": "Configuração atualizada", "config": config})


# Rota para adicionar uma nova moeda negociada
def add_stock():
    new_stock = request.json
    if "stockCode" in new_stock and "operationCode" in new_stock:
        config["STOCKS_TRADED"].append(new_stock)
        return jsonify({"message": "Moeda adicionada", "STOCKS_TRADED": config["STOCKS_TRADED"]})
    else:
        return jsonify({"error": "Parâmetros inválidos"}), 400


# Rota para remover uma moeda negociada
def remove_stock():
    stock_code = request.args.get("stockCode")
    config["STOCKS_TRADED"] = [s for s in config["STOCKS_TRADED"] if s["stockCode"] != stock_code]
    return jsonify({"message": "Moeda removida", "STOCKS_TRADED": config["STOCKS_TRADED"]})


# Definição das rotas
def setup_routes():
    app.route("/config", methods=["GET"])(get_config)
    app.route("/config", methods=["POST"])(update_config)
    app.route("/stocks", methods=["POST"])(add_stock)
    app.route("/stocks", methods=["DELETE"])(remove_stock)


setup_routes()

if __name__ == "__main__":
    app.run(debug=True)
