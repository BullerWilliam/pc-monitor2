from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, field

import mss
from PIL import Image


@dataclass
class FrameState:
    latest_frame: bytes = b""
    latest_timestamp: float = 0.0
    size: tuple[int, int] = (0, 0)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ScreenCaptureService:
    def __init__(self) -> None:
        self.state = FrameState()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name="screen-capture")
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def snapshot(self) -> tuple[bytes, float]:
        with self.state.lock:
            return self.state.latest_frame, self.state.latest_timestamp

    def size(self) -> tuple[int, int]:
        with self.state.lock:
            return self.state.size

    def _run(self) -> None:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            with self.state.lock:
                self.state.size = (int(monitor["width"]), int(monitor["height"]))

            while not self.stop_event.is_set():
                shot = sct.grab(monitor)
                image = Image.frombytes("RGB", shot.size, shot.rgb)
                image.thumbnail((1280, 720))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=65, optimize=True)
                with self.state.lock:
                    self.state.latest_frame = buffer.getvalue()
                    self.state.latest_timestamp = time.time()
                time.sleep(0.12)
