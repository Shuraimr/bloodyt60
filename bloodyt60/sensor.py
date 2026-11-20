"""Sensör tespiti ve DPI -> ham değer dönüşümü.

maxmati/a4tech-bloody-linux-driver projesindeki tablolardan uyarlanmıştır.
"""

from __future__ import annotations

from dataclasses import dataclass

CPI_VALUES_1 = [388, 787, 1192, 1582, 1974, 2359, 2749, 3153]
CPI_VALUES_2 = [4000, 250, 500, 750, 1000, 1250, 1500, 1750, 2000]

SENSOR_POWER_1 = [
    0, 0, 4, 6, 9, 11, 13, 15, 18, 20, 22, 25, 27, 29, 32, 34, 36, 39, 41, 43, 46, 48, 50,
    52, 55, 57, 59, 62, 64, 66, 69, 71, 73, 76, 78, 80, 83, 85, 87, 90, 92, 94, 97, 99, 101,
    104, 106, 108, 111, 113, 115,
]
SENSOR_POWER_2 = [
    0, 0, 4, 6, 9, 11, 14, 16, 18, 21, 23, 25, 27, 29, 32, 34, 36, 39, 41, 43, 46, 48, 50,
    52, 55, 57, 59, 62, 64, 66, 69, 72, 74, 77, 78, 80, 81, 84, 85, 88, 91, 93, 95, 98, 100,
    102, 105, 107, 109, 112, 114, 116, 119, 121, 123, 126, 128, 130, 133, 135, 137, 140, 142, 145,
]


@dataclass
class SensorInfo:
    sensor: int
    max_cpi: int
    step: int = 50
    min_cpi: int = 100

    @property
    def label(self) -> str:
        return f"PixArt PMW{self.sensor}" if self.sensor else "Bilinmeyen"


_MAJOR = {}
for ids, info in (
    ((0x1E0, 0x1CC, 0x218, 0x23C, 0x2E0, 0x480, 0x490, 0x4A0), (3325, 4000)),
    ((0x484,), (0, 12000)),
    ((0x14, 0x34, 0x38, 0x3C, 0x54, 0x5C, 0x60, 0x6C, 0xB4, 0xE0, 0xE8, 0x160, 0x164,
      0x16C, 0x184, 0x1B8, 0x238, 0x298, 0x2F0, 0x4B4, 0x4C4), (3050, 4000)),
    ((0x2B0, 0x2B4, 0x2B8, 0x49C, 0x4B8, 0x500), (3389, 16000)),
    ((0x2D4,), (9800, 12000)),
    ((0x504, 0x508), (3327, 10000)),
    ((0x4C0, 0x4D8, 0x4E0, 0x4E4), (3326, 4000)),
    ((0x4CC,), (3327, 4000)),
    ((0x4A4, 0x4BC), (3389, 4000)),
    ((0x1C, 0x30, 0x64, 0x68, 0x88, 0xA8, 0xE4, 0xEC, 0xF0, 0xF4), (9800, 8200)),
    ((0x10, 0x78, 0x290), (3305, 3200)),
):
    for i in ids:
        _MAJOR[i] = info


def detect(composite_id: int) -> SensorInfo | None:
    major = 0x10 if not (composite_id & 0xFFFC0000) else (composite_id >> 16) & 0xFFFC
    minor = composite_id & 0xFF
    if major == 0x14C:
        if minor == 0xB8:
            return None
        if minor in (0x0C, 0x0D, 0x14):
            return SensorInfo(3325, 4000)
        return SensorInfo(3050, 4000)
    if major == 0x40:
        if minor in (0xB2, 0xBC, 0x31):
            return SensorInfo(3050, 4000)
        return SensorInfo(3305, 3200)
    info = _MAJOR.get(major)
    return SensorInfo(*info) if info else None


def _u8(v: float) -> int:
    return int(v) & 0xFF


def _tc(b: int, c: int) -> int:
    d = c // 0x10
    return _u8(((d >> 1) + b) // d)


def _tc2(a: int, b: int) -> int:
    return _u8(a / (b / 64.0) + 0.5)


def _arith(x, y, clamp, bias, scale, offset=0.0):
    x, y = max(x, clamp), max(y, clamp)
    return _u8((x + bias) / scale - offset), _u8((y + bias) / scale - offset), 0


def convert(info: SensorInfo, x: int, y: int) -> tuple[int, int, int]:
    """DPI (x, y) -> (ham_x, ham_y, güç) üçlüsü."""
    x = min(x, info.max_cpi)
    y = min(y, info.max_cpi)
    s = info.sensor
    if s == 3050:
        th = 3900 if info.max_cpi >= 4000 else info.max_cpi
        x, y = min(x, th), min(y, th)
        for i in range(1, 9):
            if abs(x - CPI_VALUES_2[i]) <= 50 and abs(y - CPI_VALUES_2[i]) <= 50:
                return 0x10, 0x10, i + 0x80
        for i in range(1, 9):
            if CPI_VALUES_2[i] >= x and CPI_VALUES_2[i] >= y:
                return _tc(x, CPI_VALUES_2[i]), _tc(y, CPI_VALUES_2[i]), i + 0x80
        return _tc(x, CPI_VALUES_2[8]), _tc(y, CPI_VALUES_2[8]), 0x88
    if s == 3305:
        for i, v in enumerate(CPI_VALUES_1):
            if v == x and v == y:
                return 0x10, 0x10, i + 0x80
        for i, v in enumerate(CPI_VALUES_1):
            if v >= x and v >= y:
                return _tc(x, CPI_VALUES_1[0]), _tc(y, CPI_VALUES_1[0]), i + 0x80
        return _tc(x, CPI_VALUES_1[7]), _tc(y, CPI_VALUES_1[7]), 0x87
    if s == 3325:
        return _arith(x, y, 50.0, 22.0, 43.0, 1.0)
    if s in (3326, 3327):
        lim, table, div = (5000, SENSOR_POWER_1, 0x2B) if s == 3326 else (6200, SENSOR_POWER_2, 0x2C)
        if x > lim:
            return _tc2(x, lim), _tc2(y, lim), table[lim // 100]
        if x == y:
            return 0x40, 0x40, _u8((x + 0x16) // div - 1)
        if y > x:
            return _u8((x << 6) / y + 0.5), 0x40, table[y // 100]
        return 0x40, _u8((y << 6) / x + 0.5), table[x // 100]
    if s == 3360:
        return _arith(x, y, 100.0, 50.0, 100.0)
    if s in (3389, 9800):
        return _arith(x, y, 50.0, 25.0, 50.0)
    if s == 9500:
        return _arith(x, y, 50.0, 11.25, 22.5)
    if s == 3212:
        return _arith(x, y, 50.0, 19.0, 38.0)
    raise ValueError("Bu sensör için DPI dönüşümü bilinmiyor")
