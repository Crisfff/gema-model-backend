from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import requests
import os
import random
import time
import threading
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, db

# =============== CONFIGURACIÓN ===============
TWELVE_API_KEY = "ce11749cb6904ddf948164c0324306f3"
SYMBOL = "BTC/USD"
MODEL_URL = "https://crisdeyvid-gema-ai-model.hf.space/predict"
CRYPTO_API = "https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD"

FIREBASE_CRED = "firebase.json"  # Este archivo debe estar en la raíz
FIREBASE_URL = "https://gema-ai-model-default-rtdb.europe-west1.firebasedatabase.app"

# =============== INICIAR FIREBASE ===============
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CRED)
    firebase_admin.initialize_app(cred, {
        "databaseURL": FIREBASE_URL
    })

# =============== FASTAPI APP ===============
app = FastAPI()

# =============== FUNCIONES AUXILIARES ===============
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
    # "signal" puede llamarse así o "macd_signal"
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
    dt = datetime.now(timezone.utc) + timedelta(hours=-3)  # UTC-3 (ajusta si lo necesitas)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def update_price_exit(node_id):
    # Espera 30 minutos y actualiza el price_exit
    time.sleep(30 * 60)
    price_exit = get_btc_price()
    dt_str = now_string()
    # Actualiza en el mismo nodo
    ref = db.reference(f"signals/{node_id}")
    ref.update({
        "price_exit": price_exit,
        "datetime_exit": dt_str
    })

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
        ref = db.reference(f"signals/{node_id}")

        # Guardar datos iniciales
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
        ref.set(init_data)

        # Lanzar thread para actualizar el price_exit a los 30 minutos
        threading.Thread(target=update_price_exit, args=(node_id,), daemon=True).start()

        return JSONResponse({"node_id": node_id, "entrada": init_data})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# =============== TEST ===============
@app.get("/")
def ping():
    return {"ok": True, "msg": "Backend running!"}
