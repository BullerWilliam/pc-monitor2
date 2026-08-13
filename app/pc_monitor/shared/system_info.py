from __future__ import annotations

import os
import platform
import socket
import string
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from secrets import choice
from shutil import disk_usage
from typing import TYPE_CHECKING, Any

import psutil

if TYPE_CHECKING:
    from .models import AccessState


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_pairing_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(choice(alphabet) for _ in range(length))


def generate_device_id() -> str:
    return generate_pairing_code(12)


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
    return Path(__file__).resolve().parents[2] / "access_app.py"


def build_access_metadata(
    state: AccessState,
    started_at: str,
    capture_size: tuple[int, int],
    last_frame_timestamp: float,
    remote_interaction_requested: bool,
) -> dict[str, Any]:
    width, height = capture_size
    boot_time = int(psutil.boot_time())
    uptime_seconds = max(0, int(time.time()) - boot_time)
    system_root = Path.home().anchor or "C:\\"
    free_disk = disk_usage(system_root)
    return {
        "deviceId": state.device_id,
        "pairingCode": state.pairing_code,
        "nickname": state.nickname,
        "host": get_local_ip(),
        "port": state.port,
        "hostname": platform.node(),
        "osVersion": platform.platform(),
        "processor": platform.processor() or "Unknown processor",
        "username": Path.home().name,
        "cpuCount": os.cpu_count() or 0,
        "cpuLoadPercent": round(psutil.cpu_percent(interval=None), 1),
        "memoryPercent": round(psutil.virtual_memory().percent, 1),
        "uptimeSeconds": uptime_seconds,
        "pythonVersion": platform.python_version(),
        "screenWidth": width,
        "screenHeight": height,
        "freeDiskGb": round(free_disk.free / (1024**3), 1),
        "startedAt": started_at,
        "frameTimestamp": datetime.fromtimestamp(last_frame_timestamp or time.time(), timezone.utc).isoformat(),
        "lastSeen": utc_now(),
        "online": True,
        "streamPath": "/screen.mjpeg",
        "statusPath": "/status",
        "remoteInteractionRequested": remote_interaction_requested,
        "remoteIndicatorVisible": remote_interaction_requested,
        "remoteInteractionMode": "stub",
    }
