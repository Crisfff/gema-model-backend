import json
import os
from datetime import datetime, timezone, timedelta
from .config import LOGS_FILE

def read_logs():
    try:
        with open(LOGS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def write_logs(items):
    items = items[-500:]
    with open(LOGS_FILE, "w") as f:
        json.dump(items, f, ensure_ascii=False)

def now_iso():
    dt = datetime.now(timezone.utc) + timedelta(hours=3)  # UTC+3
    return dt.strftime("%Y-%m-%d %H:%M:%S")
