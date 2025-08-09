from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
import os

from services.config import (
    LOGS_FILE, FRONTEND_DIR, INDEX_HTML,
)
from services.logs import read_logs, write_logs, now_iso
from services.indicators import obtener_features, get_btc_price
from services.scheduler import launch_exit_updater
from services.store import save_last_node

from services.config import (
    SYMBOL, MODEL_URL, FIREBASE_URL
)
import requests
import random
import time
from datetime import datetime, timezone, timedelta

# ===== FastAPI =====
app = FastAPI()

# static/frontend
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = os.path.join(FRONTEND_DIR, INDEX_HTML)
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>frontend/index.html no encontrado</h1>", status_code=404)

# ===== Middleware de logs =====
class RequestLogger(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "-"
        method = request.method
        path = request.url.path

        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            status = 500
            raise
        finally:
            logs = read_logs()
            logs.append({
                "timestamp": now_iso(),
                "ip": f"{ip}:0",
                "method": method,
                "path": path,
                "status": status
            })
            write_logs(logs)

        return response

app.add_middleware(RequestLogger)

# ===== Endpoint para que el front lea los logs =====
@app.get("/logs")
def get_logs():
    return JSONResponse(read_logs())

# ===== Helpers locales =====
def now_string():
    # UTC+3 (ajústalo si quieres)
    dt = datetime.now(timezone.utc) + timedelta(hours=3)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# ===== Endpoint principal =====
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
        try:
            modelo_response = r.json()
        except Exception:
            modelo_response = {"error": r.text}

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

        # Crea nodo en Firebase
        url = f"{FIREBASE_URL}/signals/{node_id}.json"
        requests.put(url, json=init_data, timeout=20)

        # Guarda para el job de salida (scheduler)
        save_last_node(node_id, timestamp)

        # log extra
        logs = read_logs()
        logs.append({
            "timestamp": now_iso(),
            "ip": "local:0",
            "method": "PUT",
            "path": f"/firebase/signals/{node_id}",
            "status": 200
        })
        write_logs(logs)

        return JSONResponse({"node_id": node_id, "entrada": init_data})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# Health
@app.get("/health")
def health():
    return {"ok": True, "msg": "Backend running!"}

# ===== Lanzar scheduler en background =====
launch_exit_updater()
