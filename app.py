from fastapi import FastAPI, Request, Body, HTTPException
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
import os, json, time, random, requests
from datetime import datetime, timezone, timedelta

from services.config import (
    LOGS_FILE, FRONTEND_DIR, INDEX_HTML,
)
from services.logs import read_logs, write_logs, now_iso
from services.indicators import obtener_features, get_btc_price
from services.scheduler import launch_exit_updater
from services.store import save_last_node
from services.config import SYMBOL, MODEL_URL, FIREBASE_URL

# =================== FastAPI ===================
app = FastAPI(title="Gema Bridge + Zenith AI")

# (opcional) CORS. Si sirves el front desde el mismo dominio, puedes quitarlo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# static/frontend
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = os.path.join(FRONTEND_DIR, INDEX_HTML)
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>frontend/index.html no encontrado</h1>", status_code=404)

# =================== Middleware de logs ===================
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

# =================== Helpers ===================
def now_string():
    # UTC+3 (ajústalo si quieres)
    dt = datetime.now(timezone.utc) + timedelta(hours=3)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def fb_url(path=""):
    base = FIREBASE_URL.rstrip("/")
    return f"{base}.json" if not path else f"{base}/{path}.json"

CACHE_TTL = 8
_cache = {"db": (0, None), "memoria_viva": (0, None), "saludos": (0, None), "memoria_fija": (0, None)}

def fb_get(path="", cache_key=None):
    url = fb_url(path)
    if cache_key:
        now = time.time()
        t, data = _cache.get(cache_key, (0, None))
        if now - t < CACHE_TTL and data is not None:
            return data
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if cache_key:
        _cache[cache_key] = (time.time(), data)
    return data

def fb_put(path, payload):
    r = requests.put(fb_url(path), json=payload, timeout=10)
    # invalidar caches
    for k in _cache: _cache[k] = (0, None)
    return r.status_code == 200

def fb_patch(path, payload):
    r = requests.patch(fb_url(path), json=payload, timeout=10)
    for k in _cache: _cache[k] = (0, None)
    return r.status_code == 200

def summarize(data, limit=1500):
    try:
        s = json.dumps(data, ensure_ascii=False, indent=2)
        return s[:limit] + ("..." if len(s) > limit else "")
    except:
        return str(data)[:limit]

# Defaults (si no existen en Firebase)
DEFAULT_SALUDOS = {
    "hola": "Hola asere, ¿qué tal?",
    "q tal": "Todo bien, ¿qué quieres consultar hoy?",
    "q bola": "Aquí estoy asere, ¿qué cuentas?",
    "asere": "Dímelo, aquí estoy para lo que necesites, ¿en qué te ayudo?"
}
DEFAULT_MEMORIA_FIJA = {
    "quien eres": "Soy Zenith AI, cerebro de Gema AI Signals.",
    "quien es tu creador": "Mi creador es Cris.",
    "cual es su proposito": "Ser tu compañero y núcleo del proyecto."
}

def get_saludos():
    data = fb_get("saludos", cache_key="saludos")
    return data or DEFAULT_SALUDOS

def get_memoria_fija():
    # admite /memoria o /documentacion/memoria si luego lo mueves
    data = fb_get("memoria", cache_key="memoria_fija") or fb_get("documentacion/memoria", cache_key="memoria_fija")
    return data or DEFAULT_MEMORIA_FIJA

def norm(s: str) -> str:
    try:
        from unidecode import unidecode
        return unidecode((s or "").strip().lower())
    except:
        return (s or "").strip().lower()

# =================== Endpoints existentes ===================
@app.get("/logs")
def get_logs():
    return JSONResponse(read_logs())

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
        requests.put(fb_url(f"signals/{node_id}"), json=init_data, timeout=20)

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

# =================== NUEVO: Endpoints Firebase ===================
@app.get("/firebase")
def firebase_all():
    data = fb_get("", cache_key="db")
    return data or {}

@app.get("/firebase/signals")
def firebase_signals():
    data = fb_get("signals", cache_key="db")
    return data or {}

@app.get("/firebase/logs")
def firebase_logs():
    data = fb_get("logs", cache_key="db")
    return data or {}

# =================== NUEVO: Memoria Viva ===================
@app.get("/memoria")
def memoria_list():
    data = fb_get("memoria_viva", cache_key="memoria_viva") or {}
    out = []
    for k, v in sorted(data.items(), key=lambda x: x[0]):
        out.append({"id": k, "texto": v["texto"] if isinstance(v, dict) else v})
    return out

@app.post("/memoria")
def memoria_add(item: dict = Body(...)):
    txt = (item.get("texto") or "").strip()
    if not txt:
        raise HTTPException(400, "texto vacío")
    ts = datetime.utcnow().strftime("%Y-%m-%d-%H:%M:%S")
    ok = fb_patch("memoria_viva", {ts: {"texto": txt}})
    return {"ok": ok, "id": ts}

@app.delete("/memoria")
def memoria_clear():
    ok = fb_put("memoria_viva", {})
    return {"ok": ok}

@app.delete("/memoria/search")
def memoria_delete_contains(q: str):
    data = fb_get("memoria_viva") or {}
    dels = []
    for k, v in data.items():
        txt = v if isinstance(v, str) else v.get("texto", "")
        if norm(q) in norm(txt):
            dels.append(k)
    for k in dels:
        fb_put(f"memoria_viva/{k}", None)
    _cache["memoria_viva"] = (0, None)
    return {"ok": True, "deleted": len(dels)}

# =================== NUEVO: Chat de Zenith ===================
@app.post("/chat")
def chat(body: dict = Body(...)):
    msg_raw = (body.get("message") or "").strip()
    if not msg_raw:
        return {"reply": "Escríbeme algo 😉"}
    msg = norm(msg_raw)

    # 0) Comandos de memoria viva
    if msg.startswith("recuerda que "):
        txt = msg_raw[len("recuerda que "):].strip()
        if not txt:
            return {"reply": "Dime qué debo recordar, asere."}
        ts = datetime.utcnow().strftime("%Y-%m-%d-%H:%M:%S")
        ok = fb_patch("memoria_viva", {ts: {"texto": txt}})
        return {"reply": "✅ Anotado en mi memoria viva." if ok else "❌ No pude guardar eso ahora."}

    if msg in {"que recuerdas", "qué recuerdas", "muestra memoria", "lista memoria"}:
        arr = memoria_list()
        if not arr:
            return {"reply": "🤔 No tengo recuerdos vivos todavía."}
        bullets = "\n- ".join(x["texto"] for x in arr[-50:])
        return {"reply": "📚 Esto es lo que recuerdo:\n- " + bullets}

    if msg.startswith("olvida "):
        frag = msg_raw[len("olvida "):].strip()
        data = fb_get("memoria_viva") or {}
        dels = []
        for k, v in data.items():
            txt = v if isinstance(v, str) else v.get("texto","")
            if norm(frag) in norm(txt):
                dels.append(k)
        for k in dels:
            fb_put(f"memoria_viva/{k}", None)
        _cache["memoria_viva"] = (0, None)
        return {"reply": f"🧹 Listo, olvidé {len(dels)} recuerdo(s) que contenían “{frag}”."}

    if msg in {"borra memoria", "borra toda la memoria"}:
        fb_put("memoria_viva", {})
        return {"reply": "🧼 Memoria viva vaciada."}

    # 1) Saludos (desde Firebase si hay, sino defaults)
    saludos = get_saludos()
    for k, v in (saludos or {}).items():
        if norm(k) == msg:
            return {"reply": v}

    # 2) Memoria fija (desde Firebase si hay, sino defaults)
    memoria_fija = get_memoria_fija()
    for k, v in (memoria_fija or {}).items():
        if norm(k) == msg:
            return {"reply": v}

    # 3) Datos del proyecto (signals/logs/DB completa)
    if any(w in msg for w in ["signals", "signal", "señal", "señales"]):
        data = fb_get("signals", cache_key="db")
        return {"reply": "📊 Signals:\n\n" + (summarize(data) if data is not None else "No encontré /signals")}

    if any(w in msg for w in ["logs", "log"]):
        data = fb_get("logs", cache_key="db")
        return {"reply": "🗒 Logs:\n\n" + (summarize(data) if data is not None else "No encontré /logs")}

    if any(w in msg for w in ["firebase", "db completa", "base de datos"]):
        data = fb_get("", cache_key="db")
        return {"reply": "📡 Firebase (resumen):\n\n" + (summarize(data) if data is not None else "No pude leer la DB")}

    # 4) Fallback
    return {"reply": "Asere, eso no está en mi base ahora mismo. Dímelo con más detalle o dime: “recuerda que …” para guardarlo."}

# =================== Lanzar scheduler en background ===================
launch_exit_updater()
