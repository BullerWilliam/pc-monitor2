from __future__ import annotations

import io
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

import requests
from PIL import Image, ImageTk

from pc_monitor.shared.config import SNAPSHOT_DIR, ensure_app_dir, load_firebase_config
from pc_monitor.shared.firebase import FirebaseRegistry
from pc_monitor.shared.models import MonitorState, SavedDevice


class MultiViewWindow(tk.Toplevel):
    def __init__(self, parent: "MonitorApp") -> None:
        super().__init__(parent.root)
        self.parent = parent
        self.title("Multi-view")
        self.geometry("1180x760")
        self.labels: dict[str, tk.Label] = {}
        self.statuses: dict[str, ttk.Label] = {}
        self.refresh()

    def refresh(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        for index, device in enumerate(self.parent.state.devices):
            frame = ttk.Frame(self, padding=8)
            row = index // 2
            col = index % 2
            frame.grid(row=row, column=col, sticky="nsew")
            self.grid_columnconfigure(col, weight=1)
            self.grid_rowconfigure(row, weight=1)
            ttk.Label(frame, text=self.parent.device_title(device), font=("Segoe UI", 11, "bold")).pack(anchor="w")
            status = ttk.Label(frame, text=self.parent.device_status_text(device))
            status.pack(anchor="w")
            image_label = tk.Label(frame, bg="#101010")
            image_label.pack(fill="both", expand=True)
            self.labels[device.pairing_code] = image_label
            self.statuses[device.pairing_code] = status
        self.after(500, self.update_frames)

    def update_frames(self) -> None:
        for device in self.parent.state.devices:
            image_label = self.labels.get(device.pairing_code)
            status_label = self.statuses.get(device.pairing_code)
            if not image_label or not status_label:
                continue
            status_label.configure(text=self.parent.device_status_text(device))
            frame = self.parent.image_cache.get(device.pairing_code)
            if frame:
                image_label.configure(image=frame)
                image_label.image = frame
        if self.winfo_exists():
            self.after(500, self.update_frames)


class MonitorApp:
    def __init__(self) -> None:
        ensure_app_dir()
        self.root = tk.Tk()
        self.root.title("PC Monitor 2")
        self.root.geometry("1320x860")
        self.state = MonitorState.load()
        self.selected_code = tk.StringVar()
        self.nickname_var = tk.StringVar()
        self.remote_toggle_var = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar(value="Ready")
        self.info_text = tk.StringVar(value="No PC selected")
        self.offline_text = tk.StringVar(value="")
        self.meta_text = tk.StringVar(value="")
        self.remote_stub_text = tk.StringVar(value="Remote interaction is scaffolded only in this build.")
        self.image_cache: dict[str, ImageTk.PhotoImage] = {}
        self.pending_images: dict[str, Image.Image] = {}
        self.pending_lock = threading.Lock()
        self.device_lock = threading.Lock()
        self.stream_workers: dict[str, threading.Thread] = {}
        self.stop_events: dict[str, threading.Event] = {}
        self.multi_view_window: MultiViewWindow | None = None
        self.preview_label: tk.Label | None = None
        self.listbox: tk.Listbox | None = None
        self.registry: FirebaseRegistry | None = None
        self.registry_error = ""
        self._load_registry()
        self._build_ui()
        self._populate_devices()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(250, self.start_workers)
        self.root.after(200, self.ui_refresh_loop)

    def _load_registry(self) -> None:
        try:
            config = load_firebase_config()
            self.registry = FirebaseRegistry(config["database_url"], config["auth_token"])
        except FileNotFoundError as exc:
            self.registry_error = str(exc)
            self.registry = None
            self.status_text.set("Firebase config needed")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        left = ttk.Frame(outer, width=340)
        left.pack(side="left", fill="y")
        right = ttk.Frame(outer)
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(left, text="Paired PCs", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        button_row = ttk.Frame(left)
        button_row.pack(fill="x", pady=(8, 10))
        ttk.Button(button_row, text="Add pairing code", command=self.add_device).pack(side="left")
        ttk.Button(button_row, text="Multi-view", command=self.open_multi_view).pack(side="left", padx=(8, 0))

        if self.registry_error:
            ttk.Label(left, text=self.registry_error, foreground="#B42318", wraplength=310).pack(anchor="w", pady=(6, 0))

        self.listbox = tk.Listbox(left, height=28, exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        nick_row = ttk.Frame(left)
        nick_row.pack(fill="x", pady=(10, 0))
        ttk.Label(nick_row, text="Nickname").pack(anchor="w")
        ttk.Entry(nick_row, textvariable=self.nickname_var).pack(fill="x", pady=(4, 0))
        ttk.Button(nick_row, text="Save nickname", command=self.save_nickname).pack(anchor="w", pady=(6, 0))

        ttk.Label(right, textvariable=self.status_text, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=self.info_text, foreground="#5A5A5A", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 4))
        ttk.Label(right, textvariable=self.offline_text, foreground="#B24A00", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 10))

        remote_row = ttk.Frame(right)
        remote_row.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(
            remote_row,
            text="Enable remote interaction",
            variable=self.remote_toggle_var,
            command=self.toggle_remote_interaction,
        ).pack(side="left")
        ttk.Label(remote_row, textvariable=self.remote_stub_text, foreground="#6B7280").pack(side="left", padx=(12, 0))

        ttk.Label(right, textvariable=self.meta_text, foreground="#334155", font=("Consolas", 9), justify="left").pack(
            anchor="w", pady=(0, 10)
        )

        screen_frame = ttk.Frame(right)
        screen_frame.pack(fill="both", expand=True)
        self.preview_label = tk.Label(
            screen_frame,
            bg="#0F1720",
            fg="white",
            text="Waiting for a frame",
            width=920,
            height=600,
        )
        self.preview_label.pack(fill="both", expand=True)
        self.preview_label.bind("<Button-1>", self.on_preview_click)

    def device_title(self, device: SavedDevice) -> str:
        return device.nickname or device.pairing_code

    def device_status_text(self, device: SavedDevice) -> str:
        if self.is_recent(device.last_seen):
            return "Online"
        if device.last_seen:
            return f"Offline for {self.human_elapsed_text(device.last_seen)}"
        return "Offline"

    def _populate_devices(self) -> None:
        if not self.listbox:
            return
        self.listbox.delete(0, tk.END)
        for index, device in enumerate(self.state.devices):
            self.listbox.insert(tk.END, f"\u25cf {self.device_title(device)}")
            self.listbox.itemconfig(index, fg=("#1B7F3B" if self.is_recent(device.last_seen) else "#B42318"))

    def add_device(self) -> None:
        code = simpledialog.askstring("Pair PC", "Enter pairing code:", parent=self.root)
        if not code:
            return
        normalized = code.strip().upper()
        if any(item.pairing_code == normalized for item in self.state.devices):
            messagebox.showinfo("Already added", f"{normalized} is already in your list.", parent=self.root)
            return
        device = SavedDevice(pairing_code=normalized)
        self.state.devices.append(device)
        self.state.save()
        self._populate_devices()
        self.start_workers()

    def on_select(self, _: object) -> None:
        if not self.listbox:
            return
        selection = self.listbox.curselection()
        if not selection:
            return
        device = self.state.devices[selection[0]]
        self.selected_code.set(device.pairing_code)
        self.nickname_var.set(device.nickname)
        self.remote_toggle_var.set(device.remote_interaction_requested)
        self.update_details(device)

    def save_nickname(self) -> None:
        device = self.selected_device()
        if not device:
            return
        device.nickname = self.nickname_var.get().strip()
        self.state.save()
        self._populate_devices()
        self.update_details(device)

    def toggle_remote_interaction(self) -> None:
        device = self.selected_device()
        if not device:
            self.remote_toggle_var.set(False)
            return
        requested = bool(self.remote_toggle_var.get())
        device.remote_interaction_requested = requested
        self.state.save()
        if not self.registry:
            messagebox.showwarning(
                "Firebase config needed",
                "The local toggle changed, but Firebase is not configured yet.",
                parent=self.root,
            )
            return
        try:
            self.registry.patch_pairing(device.pairing_code, {"remoteInteractionRequested": requested})
            self.status_text.set(
                f"{self.device_title(device)} | remote interaction {'enabled' if requested else 'disabled'}"
            )
        except requests.RequestException as exc:
            self.remote_toggle_var.set(not requested)
            device.remote_interaction_requested = not requested
            self.state.save()
            messagebox.showerror("Remote interaction update failed", str(exc), parent=self.root)

    def start_workers(self) -> None:
        for device in self.state.devices:
            if device.pairing_code in self.stream_workers:
                continue
            stop_event = threading.Event()
            worker = threading.Thread(target=self.stream_device, args=(device, stop_event), daemon=True)
            self.stop_events[device.pairing_code] = stop_event
            self.stream_workers[device.pairing_code] = worker
            worker.start()

    def stream_device(self, device: SavedDevice, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            pairing = self.fetch_pairing(device)
            if not pairing:
                stop_event.wait(3)
                continue
            self.fetch_stream_frames(device, pairing, stop_event)
            stop_event.wait(1)

    def fetch_pairing(self, device: SavedDevice) -> dict[str, Any] | None:
        if not self.registry:
            return None
        try:
            pairing = self.registry.fetch_pairing(device.pairing_code)
        except requests.RequestException:
            return None
        if pairing:
            with self.device_lock:
                device.last_info = pairing
                device.last_seen = pairing.get("lastSeen", device.last_seen)
                device.remote_interaction_requested = bool(pairing.get("remoteInteractionRequested", False))
            self.state.save()
        return pairing

    def fetch_stream_frames(self, device: SavedDevice, pairing: dict[str, Any], stop_event: threading.Event) -> None:
        stream_url = f"http://{pairing.get('host')}:{pairing.get('port')}{pairing.get('streamPath', '/screen.mjpeg')}"
        started = time.monotonic()
        try:
            with requests.get(stream_url, stream=True, timeout=(4, 8)) as response:
                buffer = b""
                for chunk in response.iter_content(chunk_size=4096):
                    if stop_event.is_set() or time.monotonic() - started > 8:
                        break
                    buffer += chunk
                    while True:
                        start = buffer.find(b"\xff\xd8")
                        end = buffer.find(b"\xff\xd9")
                        if start == -1 or end == -1 or end <= start:
                            break
                        jpeg = buffer[start : end + 2]
                        buffer = buffer[end + 2 :]
                        image = Image.open(io.BytesIO(jpeg))
                        image.thumbnail((980, 680))
                        with self.pending_lock:
                            self.pending_images[device.pairing_code] = image.copy()
                        snapshot_path = SNAPSHOT_DIR / f"{device.pairing_code}.jpg"
                        image.save(snapshot_path, format="JPEG", quality=70)
                        with self.device_lock:
                            device.last_snapshot = str(snapshot_path)
                            device.last_frame_ts = datetime.now(timezone.utc).isoformat()
                        self.root.after(0, self._refresh_visible_state)
        except requests.RequestException:
            return

    def ui_refresh_loop(self) -> None:
        self._refresh_visible_state()
        self.root.after(250, self.ui_refresh_loop)

    def _refresh_visible_state(self) -> None:
        with self.pending_lock:
            pending_items = list(self.pending_images.items())
            self.pending_images.clear()

        for code, image in pending_items:
            self.image_cache[code] = ImageTk.PhotoImage(image)

        self._populate_devices()
        device = self.selected_device()
        if device:
            self.remote_toggle_var.set(device.remote_interaction_requested)
            self.update_details(device)
            frame = self.image_cache.get(device.pairing_code)
            if frame and self.preview_label:
                self.preview_label.configure(image=frame, text="")
                self.preview_label.image = frame

        if self.multi_view_window and self.multi_view_window.winfo_exists():
            self.multi_view_window.update_frames()

    def update_details(self, device: SavedDevice) -> None:
        info = device.last_info or {}
        self.status_text.set(f"{self.device_title(device)} | {self.device_status_text(device)}")
        self.info_text.set(
            f"{info.get('hostname', 'Unknown host')} | {info.get('osVersion', 'Unknown OS')} | "
            f"{info.get('host', 'No IP')}:{info.get('port', '-')}"
        )
        if self.is_recent(device.last_seen):
            self.offline_text.set("")
        else:
            self.offline_text.set(f"This PC has been offline for {self.human_elapsed_text(device.last_seen)}.")
        self.meta_text.set(self.metadata_lines(device))
        self.show_snapshot(device)

    def metadata_lines(self, device: SavedDevice) -> str:
        info = device.last_info or {}
        uptime_seconds = int(info.get("uptimeSeconds", 0) or 0)
        return "\n".join(
            [
                f"Pairing: {device.pairing_code}",
                f"Nickname: {device.nickname or '(none)'}",
                f"User: {info.get('username', 'Unknown')}",
                f"CPU: {info.get('processor', 'Unknown processor')}",
                f"CPU load: {info.get('cpuLoadPercent', '-')}%",
                f"Memory load: {info.get('memoryPercent', '-')}%",
                f"Uptime: {self.human_uptime(uptime_seconds)}",
                f"Screen: {info.get('screenWidth', '-')}x{info.get('screenHeight', '-')}",
                f"Free disk: {info.get('freeDiskGb', '-')} GB",
                f"Agent started: {self.relative_or_raw(info.get('startedAt', ''))}",
                f"Last frame: {self.relative_or_raw(device.last_frame_ts or info.get('frameTimestamp', ''))}",
                f"Remote interaction requested: {'Yes' if device.remote_interaction_requested else 'No'}",
                f"Remote mode: {info.get('remoteInteractionMode', 'unknown')}",
            ]
        )

    def show_snapshot(self, device: SavedDevice) -> None:
        if not self.preview_label:
            return
        snapshot_path = Path(device.last_snapshot) if device.last_snapshot else None
        if snapshot_path and snapshot_path.exists():
            image = Image.open(snapshot_path)
            image.thumbnail((980, 680))
            tk_image = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=tk_image, text="")
            self.preview_label.image = tk_image
        else:
            self.preview_label.configure(image="", text="No frame available yet", fg="white")

    def open_multi_view(self) -> None:
        if self.multi_view_window and self.multi_view_window.winfo_exists():
            self.multi_view_window.lift()
            return
        self.multi_view_window = MultiViewWindow(self)

    def selected_device(self) -> SavedDevice | None:
        code = self.selected_code.get()
        if not code:
            return None
        for device in self.state.devices:
            if device.pairing_code == code:
                return device
        return None

    def is_recent(self, timestamp: str) -> bool:
        if not timestamp:
            return False
        try:
            last_seen = datetime.fromisoformat(timestamp)
        except ValueError:
            return False
        return (datetime.now(timezone.utc) - last_seen).total_seconds() < 30

    def human_elapsed_text(self, timestamp: str) -> str:
        if not timestamp:
            return "an unknown amount of time"
        try:
            last_seen = datetime.fromisoformat(timestamp)
        except ValueError:
            return "an unknown amount of time"
        seconds = int((datetime.now(timezone.utc) - last_seen).total_seconds())
        if seconds < 60:
            return f"{seconds} seconds"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"

    def human_uptime(self, seconds: int) -> str:
        if seconds <= 0:
            return "Unknown"
        minutes, secs = divmod(seconds, 60)
        hours, mins = divmod(minutes, 60)
        days, hrs = divmod(hours, 24)
        if days:
            return f"{days}d {hrs}h {mins}m"
        if hours:
            return f"{hours}h {mins}m"
        return f"{minutes}m {secs}s"

    def relative_or_raw(self, timestamp: str) -> str:
        if not timestamp:
            return "Unknown"
        try:
            return f"{self.human_elapsed_text(timestamp)} ago"
        except Exception:
            return timestamp

    def on_preview_click(self, _: object) -> None:
        device = self.selected_device()
        if not device:
            return
        if not device.remote_interaction_requested:
            self.status_text.set(f"{self.device_title(device)} | click ignored because remote interaction is disabled")
            return
        self.status_text.set(
            f"{self.device_title(device)} | input relay is still a stub in this build, but the consent toggle is live"
        )

    def on_close(self) -> None:
        for stop_event in self.stop_events.values():
            stop_event.set()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = MonitorApp()
    app.run()
