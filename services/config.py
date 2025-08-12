import os
import json

# === Config por entorno (con defaults a lo que ya usas) ===
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY", "ce11749cb6904ddf948164c0324306f3")
SYMBOL        = os.getenv("SYMBOL", "BTC/USD")
MODEL_URL     = os.getenv("MODEL_URL", "https://crisdeyvid-gema-ai-model.hf.space/predict")
CRYPTO_API    = os.getenv("CRYPTO_API", "https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD")
FIREBASE_URL  = os.getenv("FIREBASE_URL", "https://moviemaniaprime-default-rtdb.firebaseio.com")

# === API Key para OpenAI ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")

# archivos
SHARED_PREFS  = os.getenv("SHARED_PREFS", "shared_preferences.json")
LOGS_FILE     = os.getenv("LOGS_FILE", "logs.json")

# frontend
FRONTEND_DIR  = os.getenv("FRONTEND_DIR", "frontend")
INDEX_HTML    = os.getenv("INDEX_HTML", "index.html")

# crea logs.json si no existe
if not os.path.exists(LOGS_FILE):
    with open(LOGS_FILE, "w") as f:
        json.dump([], f)
