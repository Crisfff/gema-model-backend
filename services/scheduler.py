import time
import requests
from datetime import datetime, timezone, timedelta
import threading

from .config import FIREBASE_URL
from .indicators import get_btc_price
from .store import load_last_node, clear_last_node
from .logs import read_logs, write_logs, now_iso

# cada cuántos segundos revisar si ya pasó media hora
CHECK_EVERY = 10
# cuánto esperar para price_exit (30 min)
EXIT_AFTER_SECONDS = 30 * 60

def _now_string():
    dt = datetime.now(timezone.utc) + timedelta(hours=3)  # UTC+3
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def updater_loop():
    while True:
        last = load_last_node()
        if last:
            now = int(time.time())
            elapsed = now - last["timestamp"]
            if elapsed >= EXIT_AFTER_SECONDS:
                node_id = last["node_id"]
                price_exit = get_btc_price()
                dt_str = _now_string()
                url = f"{FIREBASE_URL}/signals/{node_id}.json"
                payload = {
                    "price_exit": price_exit,
                    "datetime_exit": dt_str
                }
                try:
                    requests.patch(url, json=payload, timeout=20)
                    # log de actualización exit
                    logs = read_logs()
                    logs.append({
                        "timestamp": now_iso(),
                        "ip": "local:0",
                        "method": "PATCH",
                        "path": f"/firebase/signals/{node_id}",
                        "status": 200
                    })
                    write_logs(logs)
                finally:
                    clear_last_node()
        time.sleep(CHECK_EVERY)

def launch_exit_updater():
    threading.Thread(target=updater_loop, daemon=True).start()
