from fastapi import FastAPI, Request, Body, HTTPException
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
import os, json, time, random, requests, re
from datetime import datetime, timezone, timedelta

from services.config import (
    LOGS_FILE, FRONTEND_DIR, INDEX_HTML,
)
from services.logs import read_logs, write_logs, now_iso
from services.indicators import obtener_features, get_btc_price
from services.scheduler import launch_exit_updater
from services.store import save_last_node
from services.config import SYMBOL, MODEL_URL, FIREBASE_URL

# =================== OpenAI ===================
# Usamos el SDK nuevo. Modelo por defecto: gpt-4o-mini (barato/rápido y suficientemente capaz)
from openai import OpenAI
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
OPENAI_MAX_TOKENS_MONTH = int(os.getenv("OPENAI_MAX_TOKENS_MONTH", "5000000"))  # opcional
OPENAI_ALERT_TOKENS     = int(os.getenv("OPENAI_ALERT_TOKENS", "4000000"))      # opcional
_oai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# =================== FastAPI ===================
app = FastAPI(title="Gema Bridge + Zenith AI")

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
    dt = datetime.now(timezone.utc) + timedelta(hours=3)  # UTC+3
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def fb_url(path=""):
    base = FIREBASE_URL.rstrip("/")
    return f"{base}.json" if not path else f"{base}/{path}.json"

CACHE_TTL = 8
_cache = {
    "db": (0, None),
    "memoria_viva": (0, None),
    "saludos": (0, None),
    "memoria_fija": (0, None),
    "memoria_idx": (0, None),
}

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

# ---------- Normalización robusta ----------
try:
    from unidecode import unidecode
except:
    def unidecode(x): return x

def normalize_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = unidecode(s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def tokenize(s: str) -> set:
    s = normalize_key(s)
    return set(w for w in s.split() if len(w) > 2)

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
    data = fb_get("memoria", cache_key="memoria_fija") or fb_get("documentacion/memoria", cache_key="memoria_fija")
    return data or DEFAULT_MEMORIA_FIJA

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

        requests.put(fb_url(f"signals/{node_id}"), json=init_data, timeout=20)
        save_last_node(node_id, timestamp)

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

# =================== Firebase helpers públicos ===================
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

# =================== Memoria Viva (endpoints utilitarios) ===================
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
        if normalize_key(q) in normalize_key(txt):
            dels.append(k)
    for k in dels:
        fb_put(f"memoria_viva/{k}", None)
    _cache["memoria_viva"] = (0, None)
    return {"ok": True, "deleted": len(dels)}

# --- búsqueda aproximada en memoria_viva ---
def search_memoria_viva_best(query: str):
    qtokens = tokenize(query)
    data = fb_get("memoria_viva", cache_key="memoria_viva") or {}
    best, best_score = None, 0
    for k, v in data.items():
        texto = v if isinstance(v, str) else v.get("texto", "")
        score = len(tokenize(texto) & qtokens)
        if score > best_score:
            best, best_score = texto, score
    return best, best_score

# =================== Conversaciones (historial) ===================
def get_cid(body: dict) -> str:
    # Permite que el front pase un "cid" (conversation id). Si no, usa por día.
    cid = (body.get("cid") or "").strip()
    if not cid:
        cid = datetime.utcnow().strftime("default-%Y%m%d")
    return cid

def convo_path(cid: str) -> str:
    return f"conversaciones/{cid}"

def convo_add_turn(cid: str, role: str, content: str):
    ts = datetime.utcnow().strftime("%Y-%m-%d-%H:%M:%S")
    fb_patch(convo_path(cid), {ts: {"role": role, "text": content}})

def convo_get_last(cid: str, limit: int = 10):
    data = fb_get(convo_path(cid)) or {}
    items = sorted(data.items())[-limit:]
    return [{"t": k, "role": v.get("role"), "text": v.get("text")} for k, v in items]

# =================== OpenAI helpers ===================
def _get_month_key():
    now = datetime.utcnow()
    return f"usage/{now.strftime('%Y-%m')}"

def _get_usage():
    data = fb_get(_get_month_key()) or {}
    return int(data.get("tokens_used", 0))

def _add_usage(delta):
    k = _get_month_key()
    used = _get_usage() + int(delta)
    fb_patch(k, {"tokens_used": used})
    return used

def build_system_prompt():
    # Tono/persona + memoria fija + saludos (como guía)
    saludos = fb_get("saludos") or {}
    memoria_fija = fb_get("memoria") or {}
    persona = (
        "Eres Zenith AI, cerebro de Gema AI Signals. Español cubano natural, "
        "inteligente, claro, con chispa e ironía cuando haga falta (sin pasarte). "
        "No das señales; eso lo hace Gema. Respeta el proyecto y evita inventar "
        "datos técnicos si no están en Firebase. Sé breve y directa."
    )
    base = {"persona": persona, "memoria_fija": memoria_fija, "saludos": saludos}
    return json.dumps(base, ensure_ascii=False)

def ask_openai_budgeted(user_msg: str, cid: str):
    # Contexto: últimos 10 turnos de la conversación + últimos recuerdos vivos
    hist = convo_get_last(cid, limit=10)
    mem_viva = fb_get("memoria_viva") or {}
    recuerdos = []
    for k, v in sorted(mem_viva.items())[-8:]:
        txt = v if isinstance(v, str) else v.get("texto", "")
        if txt:
            recuerdos.append(txt)

    system_prompt = build_system_prompt()
    history_text = "\n".join([f"{h['role']}: {h['text']}" for h in hist])
    recuerdos_text = "\n".join(f"- {t}" for t in recuerdos)

    used = _get_usage()
    if used >= OPENAI_MAX_TOKENS_MONTH:
        return "⛔ Presupuesto de OpenAI agotado por este mes. Pruébame el próximo ciclo."

    resp = _oai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Historial reciente:\n{history_text}\n\nRecuerdos:\n{recuerdos_text}\n\nPregunta:\n{user_msg}"}
        ],
        temperature=0.5,
        max_tokens=400,
    )
    txt = resp.choices[0].message.content.strip()

    usage = getattr(resp, "usage", None)
    if usage:
        total_tokens = (getattr(usage, "total_tokens", 0)
                        or (getattr(usage, "prompt_tokens", 0) + getattr(usage, "completion_tokens", 0)))
        new_used = _add_usage(total_tokens)
        if new_used >= OPENAI_ALERT_TOKENS and new_used < OPENAI_MAX_TOKENS_MONTH:
            ts = datetime.utcnow().strftime("%Y-%m-%d-%H:%M:%S")
            fb_patch("memoria_viva", {ts: {"texto": f"⚠️ Alerta uso OpenAI: {new_used} tokens este mes"}})

    return txt

# =================== Chat de Zenith ===================
@app.post("/chat")
def chat(body: dict = Body(...)):
    msg_raw = (body.get("message") or "").strip()
    if not msg_raw:
        return {"reply": "Escríbeme algo 😉"}

    cid = get_cid(body)
    msg_norm = normalize_key(msg_raw)

    # Log turno de usuario
    convo_add_turn(cid, "user", msg_raw)

    # 0) Comandos de memoria
    if msg_norm.startswith("recuerda que "):
        resto = msg_raw[len("recuerda que "):].strip()
        m = re.match(r"(.+?)\s*=\s*(.+)", resto)
        if m:
            clave_original = m.group(1).strip()
            valor = m.group(2).strip()
            clave_norm = normalize_key(clave_original)
            ok1 = fb_patch("memoria", {clave_original: valor})
            ok2 = fb_patch("memoria_norm", {clave_norm: clave_original})
            out = "✅ Guardado: '{}'\n→ '{}'".format(clave_original, valor) if (ok1 and ok2) else "❌ No pude guardar eso ahora."
            convo_add_turn(cid, "assistant", out)
            return {"reply": out}
        else:
            ts = datetime.utcnow().strftime("%Y-%m-%d-%H:%M:%S")
            ok = fb_patch("memoria_viva", {ts: {"texto": resto}})
            out = "✅ Anotado en mi memoria viva." if ok else "❌ No pude guardar eso."
            convo_add_turn(cid, "assistant", out)
            return {"reply": out}

    if msg_norm in {"que recuerdas", "que recuerdas?", "que recuerdas ?", "muestra memoria", "lista memoria"}:
        arr = memoria_list()
        out = "🤔 No tengo recuerdos vivos todavía." if not arr else ("📚 Esto es lo que recuerdo:\n- " + "\n- ".join(x["texto"] for x in arr[-50:]))
        convo_add_turn(cid, "assistant", out)
        return {"reply": out}

    if msg_norm.startswith("olvida "):
        frag = msg_raw[len("olvida "):].strip()
        data = fb_get("memoria_viva") or {}
        dels = []
        for k, v in data.items():
            txt = v if isinstance(v, str) else v.get("texto","")
            if normalize_key(frag) in normalize_key(txt):
                dels.append(k)
        for k in dels:
            fb_put(f"memoria_viva/{k}", None)
        _cache["memoria_viva"] = (0, None)
        out = f"🧹 Listo, olvidé {len(dels)} recuerdo(s) que contenían “{frag}”."
        convo_add_turn(cid, "assistant", out)
        return {"reply": out}

    if msg_norm in {"borra memoria", "borra toda la memoria"}:
        fb_put("memoria_viva", {})
        out = "🧼 Memoria viva vaciada."
        convo_add_turn(cid, "assistant", out)
        return {"reply": out}

    # 1) Saludos (FB si hay, sino defaults)
    saludos = get_saludos()
    for k, v in (saludos or {}).items():
        if normalize_key(k) == msg_norm:
            convo_add_turn(cid, "assistant", v)
            return {"reply": v}

    # 2) Memoria fija Q/A con índice normalizado
    memoria_raw = fb_get("memoria", cache_key="memoria_fija") or {}
    memoria_idx = fb_get("memoria_norm", cache_key="memoria_idx") or {}
    if msg_norm in memoria_idx:
        clave_original = memoria_idx[msg_norm]
        if clave_original in memoria_raw:
            v = memoria_raw[clave_original]
            convo_add_turn(cid, "assistant", v)
            return {"reply": v}
    for k, v in (memoria_raw or {}).items():
        if normalize_key(k) == msg_norm:
            convo_add_turn(cid, "assistant", v)
            return {"reply": v}

    # 3) Datos del proyecto (signals/logs/DB)
    if any(w in msg_norm for w in ["signal", "signals", "senal", "senales"]):
        data = fb_get("signals", cache_key="db")
        out = "📊 Signals:\n\n" + (summarize(data) if data is not None else "No encontré /signals")
        convo_add_turn(cid, "assistant", out)
        return {"reply": out}

    if "log" in msg_norm:
        data = fb_get("logs", cache_key="db")
        out = "🗒 Logs:\n\n" + (summarize(data) if data is not None else "No encontré /logs")
        convo_add_turn(cid, "assistant", out)
        return {"reply": out}

    if any(w in msg_norm for w in ["firebase", "db completa", "base de datos"]):
        data = fb_get("", cache_key="db")
        out = "📡 Firebase (resumen):\n\n" + (summarize(data) if data is not None else "No pude leer la DB")
        convo_add_turn(cid, "assistant", out)
        return {"reply": out}

    # 3.5) Intento con memoria_viva (match por palabras)
    mv_text, mv_score = search_memoria_viva_best(msg_raw)
    if mv_text and mv_score >= 2:
        out = f"🧠 (de mi memoria) {mv_text}"
        convo_add_turn(cid, "assistant", out)
        return {"reply": out}

    # 3.8) OpenAI como cerebro auxiliar (con tono/persona/contexto)
    try:
        ai_txt = ask_openai_budgeted(msg_raw, cid)
        if ai_txt:
            convo_add_turn(cid, "assistant", ai_txt)
            return {"reply": ai_txt}
    except Exception as e:
        print("OpenAI error:", e)

    # 4) Fallback
    out = "Eso no está en mi base aún. Dímelo con más detalle o usa: “recuerda que <pregunta> = <respuesta>” para enseñarme."
    convo_add_turn(cid, "assistant", out)
    return {"reply": out}

# =================== Lanzar scheduler en background ===================
launch_exit_updater()
