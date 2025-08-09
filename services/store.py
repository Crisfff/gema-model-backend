import json
import os
from .config import SHARED_PREFS

def save_last_node(node_id: str, timestamp: int):
    with open(SHARED_PREFS, "w") as f:
        json.dump({"node_id": node_id, "timestamp": timestamp}, f)

def load_last_node():
    try:
        with open(SHARED_PREFS, "r") as f:
            return json.load(f)
    except:
        return None

def clear_last_node():
    try:
        if os.path.exists(SHARED_PREFS):
            os.remove(SHARED_PREFS)
    except:
        pass
