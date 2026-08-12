from __future__ import annotations

import argparse
import io
import json
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import disk_usage
from typing import Any
from urllib.parse import urlparse

import mss
from PIL import Image

from common import AccessState, STATE_PATH, get_executable_path, get_local_ip, load_firebase_config
from firebase_registry import FirebaseRegistry


FRAME_LOCK = threading.Lock()
LATEST_FRAME: bytes = b""
LATEST_FRAME_TS = 0.0
SHUTDOWN_EVENT = threading.Event()
CAPTURE_SIZE = {"width": 0, "height": 0}
AGENT_STARTED_AT = datetime.now(timezone.utc).isoformat()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def gather_metadata(state: AccessState) -> dict[str, Any]:
    free_disk = disk_usage(Path.home().anchor or "C:\\")
    with FRAME_LOCK:
        frame_timestamp = LATEST_FRAME_TS
    return {
        "deviceId": state.device_id,
        "pairingCode": state.pairing_code,
        "host": get_local_ip(),
        "port": state.port,
        "hostname": platform.node(),
        "os": platform.platform(),
        "processor": platform.processor(),
        "username": Path.home().name,
        "cpuCount": os.cpu_count() or 0,
        "pythonVersion": platform.python_version(),
        "screenWidth": CAPTURE_SIZE["width"],
        "screenHeight": CAPTURE_SIZE["height"],
        "freeDiskGb": round(free_disk.free / (1024**3), 1),
        "startedAt": AGENT_STARTED_AT,
        "frameTimestamp": datetime.fromtimestamp(frame_timestamp or time.time(), timezone.utc).isoformat(),
        "lastSeen": utc_now(),
        "online": True,
        "streamPath": "/screen.mjpeg",
        "statusPath": "/status",
    }


class StreamHandler(BaseHTTPRequestHandler):
    server_version = "PcMonitor2/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            self._send_json(gather_metadata(self.server.state))
            return
        if parsed.path == "/screen.mjpeg":
            self.send_response(HTTPStatus.OK)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            last_sent = 0.0
            while not SHUTDOWN_EVENT.is_set():
                with FRAME_LOCK:
                    frame = LATEST_FRAME
                    timestamp = LATEST_FRAME_TS
                if frame and timestamp != last_sent:
                    last_sent = timestamp
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                time.sleep(0.1)
            return
        self.send_error(HTTPStatus.NOT_FOUND)


class AccessServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], state: AccessState) -> None:
        super().__init__(address, handler)
        self.state = state


def capture_loop() -> None:
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        CAPTURE_SIZE["width"] = int(monitor["width"])
        CAPTURE_SIZE["height"] = int(monitor["height"])
        while not SHUTDOWN_EVENT.is_set():
            shot = sct.grab(monitor)
            image = Image.frombytes("RGB", shot.size, shot.rgb)
            image.thumbnail((1280, 720))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=60, optimize=True)
            with FRAME_LOCK:
                global LATEST_FRAME, LATEST_FRAME_TS
                LATEST_FRAME = buffer.getvalue()
                LATEST_FRAME_TS = time.time()
            time.sleep(0.2)


def heartbeat_loop(state: AccessState) -> None:
    try:
        config = load_firebase_config()
    except FileNotFoundError as exc:
        print(exc)
        return
    registry = FirebaseRegistry(config["database_url"], config["auth_token"])
    while not SHUTDOWN_EVENT.is_set():
        try:
            payload = gather_metadata(state)
            registry.put_pairing(state.pairing_code, payload)
        except Exception as exc:
            print(f"Heartbeat update failed: {exc}")
        time.sleep(10)


def install_startup_shortcut() -> None:
    startup = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
    shortcut = startup / "PcMonitor2 Access.lnk"
    target = get_executable_path()
    if getattr(sys, "frozen", False):
        shortcut_args = "run --foreground"
    else:
        shortcut_args = f'"{target}" run --foreground'
        target = Path(sys.executable)
    command = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut('{shortcut}'); "
        f"$shortcut.TargetPath = '{target}'; "
        f"$shortcut.Arguments = '{shortcut_args}'; "
        "$shortcut.WorkingDirectory = Split-Path $shortcut.TargetPath; "
        "$shortcut.Description = 'PcMonitor2 Access Agent'; "
        "$shortcut.Save();"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=True,
    )
    print(f"Installed startup shortcut at {shortcut}")


def uninstall_startup_shortcut() -> None:
    startup = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
    shortcut = startup / "PcMonitor2 Access.lnk"
    if shortcut.exists():
        shortcut.unlink()
        print(f"Removed startup shortcut at {shortcut}")
    if STATE_PATH.exists():
        STATE_PATH.unlink()
        print(f"Removed state file at {STATE_PATH}")


def run_agent(foreground: bool) -> None:
    if not foreground and "--background-child" not in sys.argv:
        if getattr(sys, "frozen", False):
            child_cmd = [str(Path(sys.executable)), "run", "--foreground", "--background-child"]
        else:
            child_cmd = [str(Path(sys.executable)), str(Path(__file__).resolve()), "run", "--foreground", "--background-child"]
        subprocess.Popen(child_cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS, close_fds=True)
        return

    state = AccessState.load_or_create()
    capture_thread = threading.Thread(target=capture_loop, daemon=True)
    heartbeat_thread = threading.Thread(target=heartbeat_loop, args=(state,), daemon=True)
    capture_thread.start()
    heartbeat_thread.start()

    server = AccessServer(("0.0.0.0", state.port), StreamHandler, state)

    def shutdown_handler(*_: object) -> None:
        SHUTDOWN_EVENT.set()
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        SHUTDOWN_EVENT.set()
        server.server_close()


def print_code() -> None:
    state = AccessState.load_or_create()
    print(state.pairing_code)


def main() -> None:
    parser = argparse.ArgumentParser(description="PcMonitor2 access agent")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the agent")
    run_parser.add_argument("--foreground", action="store_true", help="Run in the current process")
    run_parser.add_argument("--background-child", action="store_true", help=argparse.SUPPRESS)

    subparsers.add_parser("code", help="Print the pairing code")
    subparsers.add_parser("install-startup", help="Install a visible startup shortcut")
    subparsers.add_parser("uninstall", help="Remove startup shortcut and local state")

    args = parser.parse_args()
    command = args.command or "run"

    if command == "run":
        run_agent(getattr(args, "foreground", False))
    elif command == "code":
        print_code()
    elif command == "install-startup":
        install_startup_shortcut()
    elif command == "uninstall":
        uninstall_startup_shortcut()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
