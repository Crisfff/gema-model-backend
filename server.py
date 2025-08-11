import os, json, time
from datetime import datetime
from typing import Any, Dict, Optional
import requests
from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from unidecode import unidecode

PORT = int(os.environ.get("PORT", "8000"))
FIREBASE_DB_URL = os.environ.get("FIREBASE_DB_URL", "https://moviemaniaprime-default-rtdb.firebaseio.com").rstrip("/")

# ---- cargar config local (saludos/memoria fija)
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

SALUDOS = load_json("config/saludos.json", {
  "hola": "Hola asere, ¿qué tal?",
  "q tal": "Todo bien, ¿qué quieres consultar hoy?",
  "q bola": "Aquí estoy asere, ¿qué cuentas?",
  "asere": "Dímelo, aquí estoy para lo que necesites, ¿en qué te ayudo?"
})
MEMORIA_FIJA = load_json("config/memoria.json", {
  "quien eres": "Soy Zenith AI, cerebro de Gema AI Signals.",
  "quien es tu creador": "Mi creador es Cris.",
  "cual es su proposito": "Ser tu compañero y núcleo del proyecto."
})

def norm(s:str)->str: return unidecode((s or "").strip().lower())

# ---- Firebase helpers con caché suave
CACHE_TTL = 8
_cache = {"db": (0, None), "memoria_viva": (0, None)}

def fb_get(path: str = "", use_cache_key: Optional[str]=None):
    url = f"{FIREBASE_DB_URL}.json" if not path else f"{FIREBASE_DB_URL}/{path}.json"
    if use_cache_key:
        now = time.time()
        t, data = _cache.get(use_cache_key, (0, None))
        if now - t < CACHE_TTL and data is not None:
            return data
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        raise HTTPException(502, f"Firebase GET {r.status_code}")
    data = r.json()
    if use_cache_key:
        _cache[use_cache_key] = (time.time(), data)
    return data

def fb_patch(path: str, payload):
    url = f"{FIREBASE_DB_URL}/{path}.json"
    r = requests.patch(url, json=payload, timeout=10)
    _cache["db"] = (0, None); _cache["memoria_viva"] = (0, None)
    if r.status_code != 200:
        raise HTTPException(502, f"Firebase PATCH {r.status_code}")
    return True

def fb_put(path: str, payload):
    url = f"{FIREBASE_DB_URL}/{path}.json"
    r = requests.put(url, json=payload, timeout=10)
    _cache["db"] = (0, None); _cache["memoria_viva"] = (0, None)
    if r.status_code != 200:
        raise HTTPException(502, f"Firebase PUT {r.status_code}")
    return True

def summarize(data, limit=1500):
    try:
        s = json.dumps(data, ensure_ascii=False, indent=2)
        return s[:limit] + ("..." if len(s) > limit else "")
    except:
        return str(data)[:limit]

# ---- App
app = FastAPI(title="Zenith AI Core (Bridge)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restringe a tu dominio si quieres
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# servir tu frontend (carpeta frontend/)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")

# ---------- Endpoints públicos ----------
@app.get("/health")
def health():
    return {"ok": True, "firebase": FIREBASE_DB_URL}

@app.get("/firebase")
def firebase_all():
    return fb_get("", use_cache_key="db") or {}

@app.get("/signals")
def firebase_signals():
    return fb_get("signals", use_cache_key="db") or {}

@app.get("/logs")
def firebase_logs():
    return fb_get("logs", use_cache_key="db") or {}

@app.get("/memoria")
def memoria_list():
    data = fb_get("memoria_viva", use_cache_key="memoria_viva") or {}
    out = []
    for k, v in sorted(data.items(), key=lambda x: x[0]):
        out.append({"id": k, "texto": v["texto"] if isinstance(v, dict) else v})
    return out

@app.post("/memoria")
def memoria_add(item: Dict[str,str] = Body(...)):
    txt = (item.get("texto") or "").strip()
    if not txt:
        raise HTTPException(400, "texto vacío")
    ts = datetime.utcnow().strftime("%Y-%m-%d-%H:%M:%S")
    fb_patch("memoria_viva", {ts: {"texto": txt}})
    return {"ok": True, "id": ts}

@app.delete("/memoria")
def memoria_clear():
    fb_put("memoria_viva", {})
    return {"ok": True}

@app.delete("/memoria/search")
def memoria_delete_contains(q: str):
    data = fb_get("memoria_viva") or {}
    dels = []
    for k, v in data.items():
        txt = v if isinstance(v, str) else v.get("texto","")
        if norm(q) in norm(txt):
            dels.append(k)
    for k in dels:
        fb_put(f"memoria_viva/{k}", None)
    _cache["memoria_viva"] = (0, None)
    return {"ok": True, "deleted": len(dels)}

@app.post("/chat")
def chat(body: Dict[str,Any] = Body(...)):
    msg_raw = (body.get("message") or "").strip()
    if not msg_raw:
        return {"reply": "Escríbeme algo 😉"}
    msg = norm(msg_raw)

    # 1) saludos
    for k, v in SALUDOS.items():
        if norm(k) == msg:
            return {"reply": v}

    # 2) memoria fija
    for k, v in MEMORIA_FIJA.items():
        if norm(k) == msg:
            return {"reply": v}

    # 3) firebase
    if any(w in msg for w in ["signals","signal","señal","señales"]):
        return {"reply": "📊 Signals:\n\n" + summarize(fb_get("signals", use_cache_key="db"))}
    if any(w in msg for w in ["logs","log"]):
        return {"reply": "🗒 Logs:\n\n" + summarize(fb_get("logs", use_cache_key="db"))}
    if any(w in msg for w in ["firebase","db completa","base de datos"]):
        return {"reply": "📡 Firebase (resumen):\n\n" + summarize(fb_get("", use_cache_key="db"))}

    # 4) memoria viva comandos
    if msg.startswith("recuerda que "):
        txt = msg_raw[len("recuerda que "):].strip()
        if not txt:
            return {"reply":"Dime qué debo recordar, asere."}
        ts = datetime.utcnow().strftime("%Y-%m-%d-%H:%M:%S")
        fb_patch("memoria_viva", {ts: {"texto": txt}})
        return {"reply": "✅ Anotado en mi memoria viva."}

    if msg in {"que recuerdas","qué recuerdas","muestra memoria","lista memoria"}:
        arr = memoria_list()
        if not arr:
            return {"reply":"🤔 No tengo recuerdos vivos todavía."}
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

    if msg in {"borra memoria","borra toda la memoria"}:
        fb_put("memoria_viva", {})
        return {"reply": "🧼 Memoria viva vaciada."}

    # 5) fallback
    return {"reply": "Asere, eso no está en mi base ahora mismo. Dímelo con más detalle o dime: “recuerda que …” para guardarlo."}
