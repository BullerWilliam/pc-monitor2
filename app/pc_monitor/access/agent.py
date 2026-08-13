from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pc_monitor.shared.config import STATE_PATH, load_firebase_config
from pc_monitor.shared.firebase import FirebaseRegistry
from pc_monitor.shared.models import AccessState
from pc_monitor.shared.system_info import build_access_metadata, get_executable_path

from .capture import ScreenCaptureService
from .overlay import RemoteSessionOverlay


class AccessServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        state: AccessState,
        capture_service: ScreenCaptureService,
    ) -> None:
        super().__init__(address, handler)
        self.state = state
        self.capture_service = capture_service
        self.agent: AccessAgent | None = None


class StreamHandler(BaseHTTPRequestHandler):
    server_version = "PcMonitor2/2.0"

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
            frame, frame_timestamp = self.server.capture_service.snapshot()
            payload = build_access_metadata(
                self.server.state,
                self.server.started_at,
                self.server.capture_service.size(),
                frame_timestamp,
                bool(self.server.agent and self.server.agent.remote_interaction_requested),
            )
            payload["frameAvailable"] = bool(frame)
            self._send_json(payload)
            return

        if parsed.path == "/screen.mjpeg":
            self.send_response(HTTPStatus.OK)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            last_sent = 0.0
            while not self.server.shutdown_event.is_set():
                frame, frame_timestamp = self.server.capture_service.snapshot()
                if frame and frame_timestamp != last_sent:
                    last_sent = frame_timestamp
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                time.sleep(0.08)
            return

        self.send_error(HTTPStatus.NOT_FOUND)


class AccessAgent:
    def __init__(self) -> None:
        self.state = AccessState.load_or_create()
        self.capture_service = ScreenCaptureService()
        self.shutdown_event = threading.Event()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.remote_interaction_requested = False
        self.overlay: RemoteSessionOverlay | None = None
        self.registry: FirebaseRegistry | None = None

    def start(self) -> None:
        self.capture_service.start()
        self.overlay = RemoteSessionOverlay()
        self.registry = self._load_registry()
        heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True, name="firebase-heartbeat")
        heartbeat.start()

        server = AccessServer(("0.0.0.0", self.state.port), StreamHandler, self.state, self.capture_service)
        server.shutdown_event = self.shutdown_event
        server.started_at = self.started_at
        server.agent = self

        def shutdown_handler(*_: object) -> None:
            self.shutdown_event.set()
            server.shutdown()

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            self.shutdown_event.set()
            self.capture_service.stop()
            if self.overlay:
                self.overlay.close()
            server.server_close()

    def print_pairing_code(self) -> None:
        print(self.state.pairing_code)

    def install_startup_shortcut(self) -> None:
        startup = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
        startup.mkdir(parents=True, exist_ok=True)
        shortcut = startup / "PcMonitor2 Access.lnk"
        target = get_executable_path()
        if getattr(sys, "frozen", False):
            shortcut_args = "run"
        else:
            shortcut_args = f'"{target}" run'
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

    def uninstall(self) -> None:
        startup = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
        shortcut = startup / "PcMonitor2 Access.lnk"
        if shortcut.exists():
            shortcut.unlink()
            print(f"Removed startup shortcut at {shortcut}")
        if STATE_PATH.exists():
            STATE_PATH.unlink()
            print(f"Removed state file at {STATE_PATH}")

    def _load_registry(self) -> FirebaseRegistry | None:
        try:
            config = load_firebase_config()
        except FileNotFoundError as exc:
            print(exc)
            return None
        return FirebaseRegistry(config["database_url"], config["auth_token"])

    def _heartbeat_loop(self) -> None:
        while not self.shutdown_event.is_set():
            if self.registry:
                try:
                    remote_requested = False
                    pairing = self.registry.fetch_pairing(self.state.pairing_code) or {}
                    remote_requested = bool(pairing.get("remoteInteractionRequested", False))
                    if remote_requested != self.remote_interaction_requested:
                        self.remote_interaction_requested = remote_requested
                        if remote_requested and self.overlay:
                            self.overlay.show()
                        elif self.overlay:
                            self.overlay.hide()

                    _, frame_timestamp = self.capture_service.snapshot()
                    payload = build_access_metadata(
                        self.state,
                        self.started_at,
                        self.capture_service.size(),
                        frame_timestamp,
                        self.remote_interaction_requested,
                    )
                    self.registry.put_pairing(self.state.pairing_code, payload)
                except Exception as exc:
                    print(f"Heartbeat update failed: {exc}")
            self.shutdown_event.wait(5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PcMonitor2 access agent")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="Start the access agent")
    subparsers.add_parser("code", help="Print the pairing code")
    subparsers.add_parser("install-startup", help="Install a visible Startup-folder shortcut")
    subparsers.add_parser("uninstall", help="Remove the Startup-folder shortcut and local state")
    return parser
