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
        n = len(cfg.dpi_slots)
        if cfg.dpi_lock or n == 1:
            # Kilit: fareye tek kademe bildirilir, DPI tuşunun geçeceği yer kalmaz.
            dpi = cfg.dpi_slots[cfg.active_slot]
            x, y, power = sensor.convert(info, dpi, dpi)
            m.set_sensitivity(x, y, power, cfg.rate_hz, slot=0, slots=1)
        else:
            # Her kademeyi sırayla yaz, en son etkin kademe seçili kalsın.
            order = [i for i in range(n) if i != cfg.active_slot] + [cfg.active_slot]
            for i in order:
                dpi = cfg.dpi_slots[i]
                x, y, power = sensor.convert(info, dpi, dpi)
                m.set_sensitivity(x, y, power, cfg.rate_hz, slot=i, slots=n)
    m.set_backlight(cfg.backlight)
    m.set_wheel(cfg.wheel_enabled)
    return warnings
