from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests, os

# ==== CONFIGURACIÓN ====
TWELVE_API_KEY = "ce11749cb6904ddf948164c0324306f3"
SYMBOL = "BTC/USD"
MODEL_URL = "https://crisdeyvid-gema-ai-model.hf.space/predict"
INTERVAL_FILE = "interval.txt"

# ========== APP & STATIC ==========
app = FastAPI()
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("frontend/index.html")

class IntervalModel(BaseModel):
    interval: str

@app.post("/set_interval")
async def set_interval(data: IntervalModel):
    with open(INTERVAL_FILE, "w") as f:
        f.write(data.interval.strip())
    return {"ok": True, "interval": data.interval}

def get_interval():
    if not os.path.exists(INTERVAL_FILE):
        return "30min"
    with open(INTERVAL_FILE, "r") as f:
        return f.read().strip()

# ========== INDICADORES ==========
def fetch_indicator(indicator: str, symbol: str, interval: str, extra_params: str = "") -> dict:
    url = f"https://api.twelvedata.com/{indicator}?symbol={symbol}&interval={interval}&apikey={TWELVE_API_KEY}"
    if extra_params:
        url += f"&{extra_params}"
    print(f"[DEBUG] Fetching {indicator} → {url}")
    resp = requests.get(url)
    data = resp.json()
    print(f"[DEBUG] Response {indicator} → {data}")
    if "values" in data and data["values"]:
        return data["values"][0]
    raise Exception(f"Error obteniendo {indicator}: {data}")

def obtener_features(symbol: str, interval: str) -> list:
    rsi = fetch_indicator("rsi", symbol, interval)
    ema_fast = fetch_indicator("ema", symbol, interval, "time_period=12")
    ema_slow = fetch_indicator("ema", symbol, interval, "time_period=26")
    macd = fetch_indicator("macd", symbol, interval)
    features = [
        float(rsi["rsi"]),
        float(ema_fast["ema"]),
        float(ema_slow["ema"]),
        float(macd["macd"]),
        float(macd["signal"])
    ]
    print(f"[DEBUG] Features extraídas → {features}")
    return features

# ========== ENDPOINTS ==========
@app.post("/obtener_json")
async def obtener_json():
    interval = get_interval()
    print(f"[DEBUG] Interval actual → {interval}")
    try:
        features = obtener_features(SYMBOL, interval)
    except Exception as e:
        print(f"[ERROR] al obtener features → {e}")
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"features": features})

@app.post("/predict")
async def predict_for_app():
    interval = get_interval()
    print(f"[DEBUG] Interval actual → {interval}")
    try:
        features = obtener_features(SYMBOL, interval)
    except Exception as e:
        print(f"[ERROR] al obtener features → {e}")
        return JSONResponse({"error": str(e)}, status_code=400)

    payload = {"features": features}
    print(f"[DEBUG] Payload enviado al modelo → {payload}")
    try:
        r = requests.post(MODEL_URL, json=payload, timeout=20)
        print(f"[DEBUG] HTTP status modelo → {r.status_code}")
        print(f"[DEBUG] Respuesta cruda modelo → {r.text}")
        respuesta = r.json()
    except Exception as e:
        print(f"[ERROR] al contactar modelo → {e}")
        return JSONResponse({"error": f"Error al contactar el modelo: {e}"}, status_code=500)

    if "signal" not in respuesta:
        print(f"[ERROR] respuesta sin 'signal' → {respuesta}")
        return JSONResponse({"error": respuesta}, status_code=400)

    return JSONResponse({"input": features, "modelo": respuesta})

# ========== MAIN PARA LOCAL ==========
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=True)
