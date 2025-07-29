from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests, os

# ==== CONFIGURACIÓN ====
TWELVE_API_KEY = "ce11749cb6904ddf948164c0324306f3"
SYMBOL = "BTC/USD"   # Puedes cambiarlo si quieres otro par
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

def fetch_indicator(indicator, symbol, interval, extra_params=None):
    """Obtiene el último valor de un indicador de Twelve Data."""
    url = f"https://api.twelvedata.com/{indicator}?symbol={symbol}&interval={interval}&apikey={TWELVE_API_KEY}"
    if extra_params:
        url += "&" + extra_params
    resp = requests.get(url)
    data = resp.json()
    if "values" in data and len(data["values"]) > 0:
        return data["values"][0]  # último resultado
    else:
        raise Exception(f"Error obteniendo {indicator}: {data}")

def obtener_features(symbol, interval):
    # RSI
    rsi = fetch_indicator("rsi", symbol, interval)
    # EMA rápida (12)
    ema_fast = fetch_indicator("ema", symbol, interval, "time_period=12")
    # EMA lenta (26)
    ema_slow = fetch_indicator("ema", symbol, interval, "time_period=26")
    # MACD (da histograma, macd, signal)
    macd = fetch_indicator("macd", symbol, interval)

    # Extrae los valores correctos
    features = [
        float(rsi["rsi"]),
        float(ema_fast["ema"]),
        float(ema_slow["ema"]),
        float(macd["macd"]),
        float(macd["signal"]),
    ]
    return features

# ========== API PARA LA APP ==========

@app.post("/predict")
def predict_for_app():
    interval = get_interval()
    try:
        features = obtener_features(SYMBOL, interval)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    # Prepara el payload para tu modelo
    payload = {"features": features}
    try:
        r = requests.post(MODEL_URL, json=payload, timeout=15)
        respuesta = r.json()
    except Exception as e:
        return JSONResponse({"error": f"Error al contactar el modelo: {e}"}, status_code=500)
    # Retorna el resultado
    return {"input": features, "modelo": respuesta}

# ========== MAIN PARA LOCAL ==========
if name == "main":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=True)
