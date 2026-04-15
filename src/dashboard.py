from flask import Flask, jsonify, render_template_string
from src.state import stocks_traded_list, bot_status, bot_control, lock
from flask import request
import threading
import os

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-chart-financial"></script>
<script src="https://cdn.jsdelivr.net/npm/luxon"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-luxon"></script>
<style>
body { background:#0f172a; color:white; font-family:Arial; }
.card { background:#1e293b; padding:15px; margin:10px; border-radius:10px; }

button {
    padding: 10px 20px;
    border: none;
    border-radius: 8px;
    font-weight: bold;
    cursor: pointer;
    color: white;
}

#btnOn {
    background-color: #16a34a;
}

#btnOff {
    background-color: #dc2626;
}

button:hover {
    opacity: 0.8;
}

button.active {
    outline: 3px solid white;
}

.chart-card {
    height: 320px;
    display: flex;
    flex-direction: column;
    overflow: hidden; /* 🔥 impede qualquer vazamento */
}

.chart-card canvas {
    flex: 1;
}

</style>
</head>
<body>

<h1>🤖 Trading Dashboard</h1>

<div class="card">
<h2>💰 Saldo: <span id="balance"></span></h2>
</div>

<div class="card">
<h2>📊 PnL</h2>
<p id="pnl"></p>
</div>

<div class="card chart-card">
    <h2>📈 Preço</h2>
    <canvas id="priceChart"></canvas>
</div>

<div class="card">
<h2>📊 Posições</h2>
<div id="positions"></div>
</div>

<div class="card">
<h2>💼 Gestor</h2>
<p id="manager"></p>
</div>

<div class="card">
<h2>🎮 Controle do Bot</h2>

<div style="display:flex; gap:10px;">
    <button id="btnOn" onclick="toggleBot(true)">🟢 Ligar</button>
    <button id="btnOff" onclick="toggleBot(false)">🔴 Pausar</button>
</div>

<p id="statusBot">Status: ...</p>
</div>

<script>
let chart;

async function loadData() {
    const res = await fetch('/status');
    const data = await res.json();

    document.getElementById('balance').innerText = data.balance;
    
    document.getElementById('pnl').innerText =
        data.pnl + " USDT (" + data.pnl_percent + "%)";

    let html = "";
    for (let key in data.positions) {
        let p = data.positions[key];
        html += `<p>${key}: ${p.position} @ ${p.price}</p>`;
    }
    document.getElementById('positions').innerHTML = html;
    
    if (data.manager && typeof data.manager.running !== "undefined") {
        document.getElementById('manager').innerText =
            "Max posições: " + data.manager.max_positions +
            " | Status: " + (data.manager.running ? "ON" : "OFF");
    }
    
    if (typeof data.bot_running !== "undefined") {
        updateBotStatus(data.bot_running);
    }
    
    updateBotStatus(data.bot_running);
    
    updateChart(data.candles);
}

function updateChart(candles) {
    if (!candles || candles.length === 0) return;

    const ctx = document.getElementById('priceChart');

    // 👉 cria só uma vez
    if (!chart) {
        chart = new Chart(ctx, {
            type: 'candlestick',
            data: {
                datasets: [{
                    label: 'Preço',
                    data: candles
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false, // 🔥 ESSENCIAL (corrige o vazamento)
                animation: false,
                parsing: false,
                scales: {
                    x: {
                        type: 'time'
                    }
                }
            }
        });
    } else {
        // 👉 só atualiza dados
        chart.data.datasets[0].data = candles;
        chart.update();
    }
}

async function toggleBot(state) {

    const btnOn = document.getElementById("btnOn");
    const btnOff = document.getElementById("btnOff");
    const status = document.getElementById("statusBot");


    btnOn.disabled = true;
    btnOff.disabled = true;

    const oldTextOn = btnOn.innerText;
    const oldTextOff = btnOff.innerText;

    btnOn.innerText = "⏳...";
    btnOff.innerText = "⏳...";

    try {
        const res = await fetch('/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ running: state })
        });

        const data = await res.json();

        updateBotStatus(data.running);

    } catch (e) {
        console.error(e);
        status.innerText = "❌ Erro ao controlar bot";
    }

    btnOn.disabled = false;
    btnOff.disabled = false;

    btnOn.innerText = oldTextOn;
    btnOff.innerText = oldTextOff;
}

function updateBotStatus(running) {
    const status = document.getElementById("statusBot");
    const btnOn = document.getElementById("btnOn");
    const btnOff = document.getElementById("btnOff");

    if (running) {
        status.innerText = "🟢 Bot ATIVO";
        status.style.color = "#22c55e";

        btnOn.disabled = true;
        btnOff.disabled = false;

        btnOn.style.opacity = 0.5;
        btnOff.style.opacity = 1;

    } else {
        status.innerText = "🔴 Bot PAUSADO";
        status.style.color = "#ef4444";

        btnOn.disabled = false;
        btnOff.disabled = true;

        btnOn.style.opacity = 1;
        btnOff.style.opacity = 0.5;
    }
}

setInterval(loadData, 3000);
loadData();
</script>

</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/status")
def status():
    data = bot_status.copy()
    data["bot_running"] = bot_control["running"]
    return jsonify(data)

@app.route("/control", methods=["POST"])
def control():
    data = request.json

    with lock:
        bot_control["running"] = data.get("running", True)

    print("🎮 Controle recebido:", data)
    print("Estado atual:", bot_control["running"])

    return {"status": "ok", "running": bot_control["running"]}

def start_bot():
    print("🧠 Iniciando bot...")

    from src.main import trader_loop  # 🔥 IMPORT LOCAL (quebra o loop)

    for asset in stocks_traded_list:
        thread = threading.Thread(target=trader_loop, args=(asset,))
        thread.daemon = True
        thread.start()
        
def run_background():
    start_bot()

threading.Thread(target=run_background, daemon=True).start()