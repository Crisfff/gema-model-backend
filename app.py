from fastapi import FastAPI
from fastapi.responses import JSONResponse
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
FIREBASE_URL = "https://gema-ai-model-default-rtdb.europe-west1.firebasedatabase.app"

SHARED_PREFS = "shared_preferences.json"

app = FastAPI()

# ========== FUNCIONES AUXILIARES ==========
def fetch_indicator(indicator, symbol, interval, extra_params=""):
    url = f"https://api.twelvedata.com/{indicator}?symbol={symbol}&interval={interval}&apikey={TWELVE_API_KEY}"
    if extra_params:
        url += f"&{extra_params}"
    resp = requests.get(url)
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
    features = [
        float(rsi["rsi"]),
        float(ema_fast["ema"]),
        float(ema_slow["ema"]),
        float(macd["macd"]),
        float(macd.get(signal_key, 0))
    ]
    return features

def get_btc_price():
    resp = requests.get(CRYPTO_API)
    return float(resp.json().get("USD", 0))

def now_string():
    dt = datetime.now(timezone.utc) + timedelta(hours=-3)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# ====== MANEJO DE SHARED PREFERENCES (JSON LOCAL) ======
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
    try:
        if os.path.exists(SHARED_PREFS):
            os.remove(SHARED_PREFS)
    except:
        pass

# ========== ACTUALIZA PRICE_EXIT ==========
def update_price_exit_if_needed():
    while True:
        last = load_last_node()
        if last:
            now = int(time.time())
            elapsed = now - last["timestamp"]
            if elapsed >= 5 * 60:  # Cambiado a 5 minutos (antes era 30*60)
                node_id = last["node_id"]
                price_exit = get_btc_price()
                dt_str = now_string()
                url = f"{FIREBASE_URL}/signals/{node_id}.json"
                payload = {
                    "price_exit": price_exit,
                    "datetime_exit": dt_str
                }
                r = requests.patch(url, json=payload)
                # Si quieres borrar el registro después de actualizar
                clear_last_node()
        time.sleep(30)  # Revisa cada 30 segundos para más fluidez

# ======= THREAD DE ACTUALIZACIÓN EN BACKGROUND ========
threading.Thread(target=update_price_exit_if_needed, daemon=True).start()

# =============== ENDPOINT PRINCIPAL ===============
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

        # Preparar datos iniciales para Firebase
        init_data = {
            "features": features,
            "price_entry": price_entry,
            "signal": modelo_response.get("signal", ""),
            "confidence": modelo_response.get("confianza", ""),
            "timestamp": timestamp,
            "datetime": dt_str,
            "price_exit": None,
            "datetime_exit": None
        }
        # POST para crear el nodo en Firebase
        url = f"{FIREBASE_URL}/signals/{node_id}.json"
        requests.put(url, json=init_data)

        # Guarda el último nodo en el archivo local
        save_last_node(node_id, timestamp)

        return JSONResponse({"node_id": node_id, "entrada": init_data})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# =============== TEST ===============
@app.get("/")
def ping():
    return {"ok": True, "msg": "Backend running!"}
