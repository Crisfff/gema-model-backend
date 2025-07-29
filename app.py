from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests, os

# ==== CONFIGURACIÓN ====
TWELVE_API_KEY = "ce11749cb6904ddf948164c0324306f3"
SYMBOL = "BTCUSD"
MODEL_URL = "https://crisdeyvid-gema-ai-model.hf.space/predict"
INTERVAL_FILE = "interval.txt"

# ========== WEB APP ==========
app = FastAPI()
app.mount("/frontend", StaticFiles(directory="frontend", html=True), name="frontend")

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("frontend/index.html")

class IntervalModel(BaseModel):
    interval: str

@app.post("/set_interval")
def set_intv(data: IntervalModel):
    with open(INTERVAL_FILE, "w") as f:
        f.write(data.interval.strip())
    return {"ok": True, "interval": data.interval}

def get_interval():
    if not os.path.exists(INTERVAL_FILE):
        return "30min"
    with open(INTERVAL_FILE, "r") as f:
        return f.read().strip()

# ========== INDICADORES ==========
def fetch_indicator(indicator, symbol, interval):
    url = f"https://api.twelvedata.com/{indicator}?symbol={symbol.replace('/', '')}&interval={interval}&apikey={TWELVE_API_KEY}"
    # Para EMA se agrega time_period
    if "ema" in indicator:
        if "&time_period=12" in interval or "&time_period=26" in interval:
            url = f"https://api.twelvedata.com/{indicator}?symbol={symbol.replace('/', '')}&interval={interval}&apikey={TWELVE_API_KEY}"
        else:
            url = url + "&time_period=12" if "fast" in indicator else url + "&time_period=26"
    print("URL Indicator:", url)
    resp = requests.get(url)
    data = resp.json()
    print("Response Indicator:", data)
    if "values" in data and len(data["values"]) > 0:
        return data["values"][0]  # último resultado
    else:
        raise Exception(f"Error obteniendo {indicator}: {data}")

def obtener_features(symbol, interval):
    # RSI
    rsi = fetch_indicator("rsi", symbol, interval)
    # EMA rápida (12)
    ema_fast = fetch_indicator("ema", symbol, interval + "&time_period=12")
    # EMA lenta (26)
    ema_slow = fetch_indicator("ema", symbol, interval + "&time_period=26")
    # MACD
    macd = fetch_indicator("macd", symbol, interval)
    # Construye features
    features = [
        float(rsi["rsi"]),
        float(ema_fast["ema"]),
        float(ema_slow["ema"]),
        float(macd["macd"]),
        float(macd["signal"]),
    ]
    print("Features extraídas:", features)
    return features

# ========== API PARA LA APP ==========
@app.post("/predict")
def predict_for_app():
    interval = get_interval()
    print(f"Interval actual: {interval}")
    try:
        features = obtener_features(SYMBOL, interval)
        print("Features obtenidas:", features)
    except Exception as e:
        print("Error obteniendo features:", e)
        return JSONResponse({"error": str(e)}, status_code=400)
    payload = {"features": features}
    print("Payload enviado al modelo:", payload)
    try:
        r = requests.post(MODEL_URL, json=payload, timeout=20)
        print("HTTP status modelo:", r.status_code)
        respuesta = r.json()
        print("Respuesta del modelo:", respuesta)
    except Exception as e:
        print("Error contactando modelo:", e)
        return JSONResponse({"error": f"Error al contactar el modelo: {e}"}, status_code=500)
    if "signal" not in respuesta:
        print("Respuesta sin 'signal':", respuesta)
        return JSONResponse({"error": respuesta}, status_code=400)
    return {"input": features, "modelo": respuesta}

# ========== MAIN PARA LOCAL ==========
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=True)
