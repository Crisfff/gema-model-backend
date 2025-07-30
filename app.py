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

# ================= CONFIGURACIÓN ====================
TWELVE_API_KEY = "ce11749cb6904ddf948164c0324306f3"
SYMBOL = "BTC/USD"
MODEL_URL = "https://crisdeyvid-gema-ai-model.hf.space/predict"
CRYPTO_API = "https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD"

# ---- Credenciales de Firebase (ajusta la ruta al tuyo) ----
FIREBASE_CRED = "firebase.json"  # Debes subir este archivo
FIREBASE_URL = "https://gema-ai-model-default-rtdb.europe-west1.firebasedatabase.app"

# ================= INICIAR FIREBASE ==================
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CRED)
    firebase_admin.initialize_app(cred, {
        "databaseURL": FIREBASE_URL
    })

# ================== FASTAPI ==========================
app = FastAPI()

# ================== INDICADORES ======================
def fetch_indicator(indicator, symbol, interval, extra_params=""):
    url = f"https://api.twelvedata.com/{indicator}?symbol={symbol.replace('/','')}&interval={interval}&apikey={TWELVE_API_KEY}"
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
    dt = datetime.now(timezone.utc) + timedelta(hours=-3)  # Ajusta a tu zona si quieres
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# =============== FLUJO PRINCIPAL ======================
@app.post("/full_signal")
def full_signal():
    try:
        # 1. Features e intervalo
        interval = "30min"
        features = obtener_features(SYMBOL, interval)
        # 2. Precio de entrada
        price_entry = get_btc_price()
        # 3. Timestamp y hora legible
        timestamp = int(time.time())
        dt_str = now_string()
        # 4. Enviar al modelo
        payload = {"features": features}
        r = requests.post(MODEL_URL, json=payload, timeout=20)
        modelo_response = r.json()
        # 5. Nodo aleatorio
        node_id = "".join([str(random.randint(0, 9)) for _ in range(5)])
        path = f"Signal/{node_id}"
        # 6. Guardar todo en Firebase
        init_data = {
            "features": features,
            "price_entry": price_entry,
            "signal": modelo_response.get("signal", ""),
            "confidence": modelo_response.get("confianza", ""),
            "timestamp": timestamp,
            "datetime": dt_str,
        }
        db.reference(path).set(init_data)

        # 7. Iniciar el thread para esperar 30 min y actualizar
        def update_exit_price(node_id):
            time.sleep(1800)  # 30 min
            price_exit = get_btc_price()
            dt_exit = now_string()
            db.reference(f"Signal/{node_id}").update({
                "price_exit": price_exit,
                "exit_time": dt_exit,
                "exit_timestamp": int(time.time())
            })

        threading.Thread(target=update_exit_price, args=(node_id,)).start()

        return JSONResponse({
            "ok": True,
            "path": path,
            "data": init_data,
            "info": "Señal generada y guardada. price_exit se actualizará en 30 minutos."
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# =============== FIN FASTAPI =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=True)
