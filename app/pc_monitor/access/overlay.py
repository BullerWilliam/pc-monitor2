from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk


class RemoteSessionOverlay:
    def __init__(self) -> None:
        self.commands: "queue.Queue[bool | None]" = queue.Queue()
        self.thread = threading.Thread(target=self._ui_thread, daemon=True, name="remote-overlay")
        self.thread.start()

    def show(self) -> None:
        self.commands.put(True)

    def hide(self) -> None:
        self.commands.put(False)

    def close(self) -> None:
        self.commands.put(None)
        self.thread.join(timeout=2)

    def _ui_thread(self) -> None:
        root = tk.Tk()
        root.title("Remote session active")
        root.geometry("340x86+20+20")
        root.attributes("-topmost", True)
        root.resizable(False, False)

        frame = ttk.Frame(root, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Remote session active", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="This indicator is shown because monitor.exe enabled remote interaction.",
            wraplength=300,
        ).pack(anchor="w", pady=(6, 0))

        root.withdraw()

        def process_queue() -> None:
            while True:
                try:
                    command = self.commands.get_nowait()
                except queue.Empty:
                    break
                if command is None:
                    root.destroy()
                    return
                if command:
                    root.deiconify()
                else:
                    root.withdraw()
            root.after(150, process_queue)

        root.after(150, process_queue)
        root.mainloop()
