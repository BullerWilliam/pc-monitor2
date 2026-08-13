from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .config import MONITOR_STATE_PATH, STATE_PATH
from .storage import load_json, save_json
from .system_info import find_free_port, generate_device_id, generate_pairing_code


@dataclass
class AccessState:
    device_id: str
    pairing_code: str
    port: int
    nickname: str = ""

    @classmethod
    def load_or_create(cls) -> "AccessState":
        data = load_json(STATE_PATH, None)
        if data:
            return cls(**data)
        state = cls(
            device_id=generate_device_id(),
            pairing_code=generate_pairing_code(6),
            port=find_free_port(),
        )
        state.save()
        return state

    def save(self) -> None:
        save_json(STATE_PATH, asdict(self))


@dataclass
class SavedDevice:
    pairing_code: str
    nickname: str = ""
    last_info: dict[str, Any] | None = None
    last_seen: str = ""
    last_snapshot: str = ""
    last_frame_ts: str = ""
    remote_interaction_requested: bool = False


@dataclass
class MonitorState:
    devices: list[SavedDevice] = field(default_factory=list)

    @classmethod
    def load(cls) -> "MonitorState":
        raw = load_json(MONITOR_STATE_PATH, {"devices": []})
        devices = [SavedDevice(**item) for item in raw.get("devices", [])]
        return cls(devices=devices)

    def save(self) -> None:
        save_json(MONITOR_STATE_PATH, {"devices": [asdict(item) for item in self.devices]})
