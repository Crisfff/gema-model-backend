import requests
from .config import TWELVE_API_KEY, CRYPTO_API

def fetch_indicator(indicator: str, symbol: str, interval: str, extra_params: str = "") -> dict:
    url = f"https://api.twelvedata.com/{indicator}?symbol={symbol}&interval={interval}&apikey={TWELVE_API_KEY}"
    if extra_params:
        url += f"&{extra_params}"
    resp = requests.get(url, timeout=20)
    data = resp.json()
    if "values" in data and data["values"]:
        return data["values"][0]
    raise Exception(f"Error obteniendo {indicator}: {data}")

def obtener_features(symbol: str, interval: str) -> list:
    rsi       = fetch_indicator("rsi", symbol, interval)
    ema_fast  = fetch_indicator("ema", symbol, interval, "time_period=12")
    ema_slow  = fetch_indicator("ema", symbol, interval, "time_period=26")
    macd      = fetch_indicator("macd", symbol, interval)

    signal_key = "signal" if "signal" in macd else "macd_signal"
    features = [
        float(rsi["rsi"]),
        float(ema_fast["ema"]),
        float(ema_slow["ema"]),
        float(macd["macd"]),
        float(macd.get(signal_key, 0))
    ]
    return features

def get_btc_price() -> float:
    resp = requests.get(CRYPTO_API, timeout=15)
    return float(resp.json().get("USD", 0))
