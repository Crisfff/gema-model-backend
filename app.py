from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import requests
import random
import time
import threading
import json
from datetime import datetime, timezone, timedelta
import os

# ================= CONFIGURACIÓN =================
TWELVE_API_KEY = "ce11749cb6904ddf948164c0324306f3"
SYMBOL = "BTC/USD"
MODEL_URL = "https://crisdeyvid-gema-ai-model.hf.space/predict"
CRYPTO_API = "https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD"
FIREBASE_URL = "https://moviemaniaprime-default-rtdb.firebaseio.com"

SHARED_PREFS = "shared_preferences.json"
LOGS_FILE = "logs.json"
INTERVAL_FILE = "interval.json"

app = FastAPI()

# ====== SERVIR FRONTEND ======
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = os.path.join("frontend", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>frontend/index.html no encontrado</h1>", status_code=404)

# ====== FUNCIONES AUXILIARES ======
def fetch_indicator(indicator, symbol, interval, extra_params=""):
    url = f"https://api.twelvedata.com/{indicator}?symbol={symbol}&interval={interval}&apikey={TWELVE_API_KEY}"
    if extra_params:
        url += f"&{extra_params}"
    resp = requests.get(url, timeout=20)
    data = resp.json()
    if "values" in data and data["values"]:
        return data["values"][0]
    raise Exception(f"Error obteniendo {indicator}: {data}")

def obtener_features(symbol, interval):
    rsi = fetch_indicator("rsi", symbol, interval)
    ema_fast = fetch_indicator("ema", symbol, interval, "time_period=12")
    ema_slow = fetch_indicator("ema", symbol, interval, "time_period=26")
    macd = fetch_indicator("macd", symbol, interval)
    signal_key = "signal" if "signal" in macd else "macd_signal"
    return [
        float(rsi["rsi"]),
        float(ema_fast["ema"]),
        float(ema_slow["ema"]),
        float(macd["macd"]),
        float(macd.get(signal_key, 0))
    ]

def get_btc_price():
    resp = requests.get(CRYPTO_API, timeout=15)
    return float(resp.json().get("USD", 0))

def now_string():
    dt = datetime.now(timezone.utc) + timedelta(hours=3)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def save_last_node(node_id, timestamp):
    with open(SHARED_PREFS, "w") as f:
        json.dump({"node_id": node_id, "timestamp": timestamp}, f)

def load_last_node():
    try:
        with open(SHARED_PREFS, "r") as f:
            return json.load(f)
    except:
        return None

def clear_last_node():
    if os.path.exists(SHARED_PREFS):
        os.remove(SHARED_PREFS)

# ====== LOGGING ======
def add_log(ip, method, path, status):
    log_entry = {
        "ts": now_string(),
        "ip": ip,
        "method": method,
        "path": path,
        "status": status
    }
    logs = []
    if os.path.exists(LOGS_FILE):
        try:
            with open(LOGS_FILE, "r") as f:
                logs = json.load(f)
        except:
            logs = []
    logs.append(log_entry)
    logs = logs[-200:]  # guardamos solo los últimos 200
    with open(LOGS_FILE, "w") as f:
        json.dump(logs, f)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    ip = request.client.host
    method = request.method
    path = request.url.path
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        status = 500
        raise
    finally:
        add_log(ip, method, path, status)
    return response

# ====== INTERVALO ======
def save_interval(minutes):
    with open(INTERVAL_FILE, "w") as f:
        json.dump({"interval": minutes}, f)

def load_interval():
    if os.path.exists(INTERVAL_FILE):
        try:
            with open(INTERVAL_FILE, "r") as f:
                return json.load(f).get("interval", "")
        except:
            return ""
    return ""

@app.post("/set_interval")
async def set_interval(data: dict):
    interval = data.get("interval", "").strip()
    save_interval(interval)
    return {"ok": True, "interval": interval}

@app.get("/current_interval")
async def current_interval():
    return {"interval": load_interval()}

@app.get("/logs")
async def get_logs(limit: int = 200):
    if os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, "r") as f:
            logs = json.load(f)
        return {"logs": logs[-limit:]}
    return {"logs": []}

# ====== THREAD DE PRICE_EXIT ======
def update_price_exit_if_needed():
    while True:
        last = load_last_node()
        if last:
            now = int(time.time())
            elapsed = now - last["timestamp"]
            if elapsed >= 30 * 60:  # 30 min
                node_id = last["node_id"]
                price_exit = get_btc_price()
                dt_str = now_string()
                url = f"{FIREBASE_URL}/signals/{node_id}.json"
                payload = {
                    "price_exit": price_exit,
                    "datetime_exit": dt_str
                }
                try:
                    requests.patch(url, json=payload, timeout=20)
                    add_log("SYSTEM", "PATCH", f"/signals/{node_id}", 200)
                except:
                    add_log("SYSTEM", "PATCH", f"/signals/{node_id}", 500)
                finally:
                    clear_last_node()
        time.sleep(10)

threading.Thread(target=update_price_exit_if_needed, daemon=True).start()

# ====== ENDPOINT PRINCIPAL ======
@app.post("/full_signal")
def full_signal():
    try:
        interval = "30min"
        features = obtener_features(SYMBOL, interval)
        price_entry = get_btc_price()
        timestamp = int(time.time())
        dt_str = now_string()
        payload = {"features": features}
        r = requests.post(MODEL_URL, json=payload, timeout=20)
        modelo_response = r.json()

        node_id = "".join([str(random.randint(0, 9)) for _ in range(5)])
        init_data = {
            "Id_nodo": node_id,
            "features": features,
            "price_entry": price_entry,
            "signal": modelo_response.get("signal", ""),
            "confidence": modelo_response.get("confianza", ""),
            "timestamp": timestamp,
            "datetime": dt_str,
            "price_exit": None,
            "datetime_exit": None
        }
        url = f"{FIREBASE_URL}/signals/{node_id}.json"
        requests.put(url, json=init_data, timeout=20)

        save_last_node(node_id, timestamp)
        add_log("SYSTEM", "PUT", f"/signals/{node_id}", 200)

        return JSONResponse({"node_id": node_id, "entrada": init_data})
    except Exception as e:
        add_log("SYSTEM", "POST", "/full_signal", 500)
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/health")
def health():
    return {"ok": True, "msg": "Backend running!"}
