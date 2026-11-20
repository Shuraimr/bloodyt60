"""Ayarları fareye uygular."""

from __future__ import annotations

from . import sensor
from .config import Config
from .protocol import BloodyMouse, MouseError


def mouse_sensor(m: BloodyMouse) -> sensor.SensorInfo | None:
    try:
        return sensor.detect(m.composite_id())
    except MouseError:
        return None


def apply_config(m: BloodyMouse, cfg: Config, info: sensor.SensorInfo | None = None) -> list[str]:
    """Ayarları uygular; uyarı listesi döndürür."""
    warnings = []
    info = info or mouse_sensor(m)
    if info is None:
        warnings.append("Sensör tanınmadı; DPI/Hz uygulanamadı.")
    else:
        dpi = cfg.dpi_slots[cfg.active_slot]
        x, y, power = sensor.convert(info, dpi, dpi)
        m.set_sensitivity(
            x, y, power, cfg.rate_hz, slot=cfg.active_slot, slots=len(cfg.dpi_slots)
        )
    m.set_backlight(cfg.backlight)
    m.set_wheel(cfg.wheel_enabled)
    return warnings
