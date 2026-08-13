from __future__ import annotations

import os
from pathlib import Path

from .storage import load_json


APP_NAME = "PcMonitor2"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
STATE_PATH = APP_DIR / "access_state.json"
MONITOR_STATE_PATH = APP_DIR / "monitor_state.json"
SNAPSHOT_DIR = APP_DIR / "snapshots"
FIREBASE_CONFIG_NAMES = [
    Path.cwd() / "firebase_config.json",
    APP_DIR / "firebase_config.json",
]


def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR


def load_firebase_config() -> dict[str, str]:
    for path in FIREBASE_CONFIG_NAMES:
        if path.exists():
            data = load_json(path, {})
            if data.get("database_url"):
                return {
                    "database_url": str(data["database_url"]).rstrip("/"),
                    "auth_token": str(data.get("auth_token", "")),
                }
    raise FileNotFoundError(
        "Missing firebase_config.json. Create one in the repo root or in %APPDATA%\\PcMonitor2."
    )
