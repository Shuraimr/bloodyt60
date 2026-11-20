"""Kalıcı ayarlar (~/.config/bloodyt60/config.json)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "bloodyt60"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


@dataclass
class Config:
    rate_hz: int = 1000
    dpi_slots: list[int] = field(default_factory=lambda: [800, 1600, 2400, 3200])
    active_slot: int = 0
    dpi_lock: bool = False
    backlight: int = 3
    wheel_enabled: bool = True
    debounce_enabled: bool = False
    debounce_ms: int = 8
    min_click_ms: int = 0

    @classmethod
    def load(cls) -> "Config":
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cls()
        cfg = cls()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        cfg.dpi_slots = [int(x) for x in cfg.dpi_slots][:5] or [800]
        cfg.active_slot = min(max(0, cfg.active_slot), len(cfg.dpi_slots) - 1)
        return cfg

    def save(self) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(self), f, indent=2)
        os.replace(tmp, CONFIG_PATH)

    @staticmethod
    def mtime() -> float:
        try:
            return os.stat(CONFIG_PATH).st_mtime
        except OSError:
            return 0.0
