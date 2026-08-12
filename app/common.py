from __future__ import annotations

import json
import os
import socket
import string
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from secrets import choice
from typing import Any


APP_NAME = "PcMonitor2"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
STATE_PATH = APP_DIR / "access_state.json"
MONITOR_STATE_PATH = APP_DIR / "monitor_state.json"
FIREBASE_CONFIG_NAMES = [
    Path.cwd() / "firebase_config.json",
    APP_DIR / "firebase_config.json",
]


def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data: Any) -> None:
    ensure_app_dir()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def generate_pairing_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(choice(alphabet) for _ in range(length))


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        return int(sock.getsockname()[1])


def get_local_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def get_executable_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(__file__).resolve().parent / "access_app.py"


@dataclass
class AccessState:
    device_id: str
    pairing_code: str
    port: int

    @classmethod
    def load_or_create(cls) -> "AccessState":
        data = load_json(STATE_PATH, None)
        if data:
            return cls(**data)
        state = cls(
            device_id=generate_pairing_code(12),
            pairing_code=generate_pairing_code(6),
            port=find_free_port(),
        )
        save_json(STATE_PATH, asdict(state))
        return state

    def save(self) -> None:
        save_json(STATE_PATH, asdict(self))


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
