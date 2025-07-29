from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests, os, json

# ==== CONFIGURACIÓN ====
TWELVE_API_KEY = "ce11749cb6904ddf948164c0324306f3"
SYMBOL = "BTC/USD"    # Usar barra para TwelveData
MODEL_URL = "https://crisdeyvid-gema-ai-model.hf.space/predict"
INTERVAL_FILE = "interval.txt"

# ========== WEB APP ==========
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
def fetch_indicator(indicator, symbol, interval, extra=""):
    url = f"https://api.twelvedata.com/{indicator}?symbol={symbol}&interval={interval}&apikey={TWELVE_API_KEY}{extra}"
    resp = requests.get(url)
    data = resp.json()
    if "values" in data and len(data["values"]) > 0:
        return data["values"][0]
    else:
        raise Exception(f"Error obteniendo {indicator}: {data}")

def obtener_features(symbol, interval):
    rsi = fetch_indicator("rsi", symbol, interval)
    ema_fast = fetch_indicator("ema", symbol, interval, "&time_period=12")
    ema_slow = fetch_indicator("ema", symbol, interval, "&time_period=26")
    macd = fetch_indicator("macd", symbol, interval)
    features = [
        float(rsi["rsi"]),
        float(ema_fast["ema"]),
        float(ema_slow["ema"]),
        float(macd["macd"]),
        float(macd["signal"]),
    ]
    return features

@app.post("/obtener_json")
async def obtener_json():
    interval = get_interval()
    try:
        features = obtener_features(SYMBOL, interval)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    json_data = {
        "features": features
    }
    return JSONResponse(content=json_data)

# Opcional: endpoint para enviar a modelo si lo quieres agregar después
@app.post("/enviar_a_modelo")
async def enviar_a_modelo():
    interval = get_interval()
    try:
        features = obtener_features(SYMBOL, interval)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    payload = {"features": features}
    r = requests.post(MODEL_URL, json=payload, timeout=20)
    return r.json()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860)
