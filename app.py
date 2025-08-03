from fastapi import FastAPI
from fastapi.responses import JSONResponse
import requests
import random
import time
from datetime import datetime, timezone, timedelta

# ====== CONFIGURACIÓN ======
TWELVE_API_KEY = "ce11749cb6904ddf948164c0324306f3"
SYMBOL = "BTC/USD"
MODEL_URL = "https://crisdeyvid-gema-ai-model.hf.space/predict"
CRYPTO_API = "https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD"
FIREBASE_URL = "https://gema-ai-model-default-rtdb.europe-west1.firebasedatabase.app"

# ====== FASTAPI APP ======
app = FastAPI()

# ====== FUNCIONES DE AYUDA ======
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
    dt = datetime.now(timezone.utc) + timedelta(hours=-3)  # UTC-3 Cuba, cambia si quieres
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# ====== CREAR NUEVA SEÑAL ======
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
        requests.put(url, json=init_data)
        return JSONResponse({"node_id": node_id, "entrada": init_data})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ====== ACTUALIZAR PRECIO DE SALIDA POR CRON ======
@app.post("/update_price_exit")
def update_price_exit():
    try:
        # 1. Obtener todos los signals de Firebase
        url = f"{FIREBASE_URL}/signals.json"
        resp = requests.get(url)
        data = resp.json()
        now = int(time.time())
        actualizados = []
        for node_id, node in (data or {}).items():
            # Si ya tiene price_exit, saltar
            if node.get("price_exit") is not None:
                continue
            # Si aún no han pasado 30 minutos, saltar
            ts = node.get("timestamp", 0)
            if now - int(ts) < 30*60:
                continue
            # Actualizar
            price_exit = get_btc_price()
            dt_str = now_string()
            update_payload = {
                "price_exit": price_exit,
                "datetime_exit": dt_str
            }
            up_url = f"{FIREBASE_URL}/signals/{node_id}.json"
            requests.patch(up_url, json=update_payload)
            actualizados.append(node_id)
        return {"updated": actualizados}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ====== TEST ======
@app.get("/")
def ping():
    return {"ok": True, "msg": "Backend running!"}
