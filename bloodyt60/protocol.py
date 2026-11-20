"""A4Tech Bloody fare protokolü (hidraw feature report üzerinden).

Fare, 2 numaralı arayüzde üretici sayfası 0xFF31 olan bir HID koleksiyonu
sunar. Rapor kimliği 0x07 olan 72 baytlık feature raporları ile konuşulur:

    [0] 0x07   rapor kimliği
    [1] opcode
    [2..7]     alt komut / adres / okuma-yazma bayrağı
    [8..]      veri

Bilinen opcode'lar topluluk tarafından tersine mühendislikle bulunmuştur
(maxmati/a4tech-bloody-linux-driver, C0rn3j/a4tech_bloody_p85_driver).
"""

from __future__ import annotations

import fcntl
import glob
import os
from dataclasses import dataclass

A4TECH_VID = 0x09DA
REPORT_ID = 0x07
REPORT_SIZE = 72

OP_REBOOT = 0x00
OP_MEMORY = 0x02
OP_DEVICE_INFO = 0x05
OP_SENSITIVITY = 0x0D
OP_BACKLIGHT = 0x11
OP_CALIBRATION = 0x13
OP_WHEEL = 0x16
OP_DEVICE_INFO_2 = 0x1F

# Rapor hızı baytı aslında "kaç ms'de bir" değeridir.
RATE_TO_BYTE = {1000: 0x01, 500: 0x02, 250: 0x04, 125: 0x08}
BYTE_TO_RATE = {v: k for k, v in RATE_TO_BYTE.items()}

KNOWN_MODELS = {
    0x7C5E: "Bloody T60",
}

# --- ioctl yardımcıları ----------------------------------------------------

_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, typ: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (typ << 8) | nr


def HIDIOCSFEATURE(length: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, ord("H"), 0x06, length)


def HIDIOCGFEATURE(length: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, ord("H"), 0x07, length)


class MouseError(Exception):
    pass


@dataclass
class HidrawInfo:
    path: str
    vid: int
    pid: int
    name: str
    phys: str


def _read_uevent(sysdir: str) -> dict[str, str]:
    out = {}
    try:
        with open(os.path.join(sysdir, "device", "uevent")) as f:
            for line in f:
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    out[k] = v
    except OSError:
        pass
    return out


def _has_vendor_page(sysdir: str) -> bool:
    try:
        with open(os.path.join(sysdir, "device", "report_descriptor"), "rb") as f:
            desc = f.read()
    except OSError:
        return False
    # Usage Page (Vendor 0xFF31) + Report ID 7
    return b"\x06\x31\xff" in desc and b"\x85\x07" in desc


def find_devices() -> list[HidrawInfo]:
    """Yapılandırma arayüzüne sahip Bloody hidraw düğümlerini listeler."""
    found = []
    for sysdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        ue = _read_uevent(sysdir)
        hid_id = ue.get("HID_ID", "")
        try:
            _bus, vid, pid = (int(x, 16) for x in hid_id.split(":"))
        except ValueError:
            continue
        if vid != A4TECH_VID or not _has_vendor_page(sysdir):
            continue
        found.append(
            HidrawInfo(
                path="/dev/" + os.path.basename(sysdir),
                vid=vid,
                pid=pid,
                name=KNOWN_MODELS.get(pid, ue.get("HID_NAME", "Bloody").strip()),
                phys=ue.get("HID_PHYS", ""),
            )
        )
    return found


@dataclass
class DpiSlot:
    x: int  # ham sensör değeri
    y: int


class BloodyMouse:
    def __init__(self, info: HidrawInfo):
        self.info = info
        try:
            self.fd = os.open(info.path, os.O_RDWR)
        except PermissionError as e:
            raise MouseError(
                f"{info.path} açılamadı: izin yok. install-udev.sh ile udev "
                "kuralını kurup fareyi yeniden tak."
            ) from e

    @classmethod
    def open_first(cls) -> "BloodyMouse":
        devs = find_devices()
        if not devs:
            raise MouseError("Bloody fare bulunamadı.")
        return cls(devs[0])

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- ham G/Ç -----------------------------------------------------------

    @staticmethod
    def _packet(opcode: int, fields: dict[int, int] | None = None) -> bytearray:
        buf = bytearray(REPORT_SIZE)
        buf[0] = REPORT_ID
        buf[1] = opcode
        for idx, val in (fields or {}).items():
            buf[idx] = val & 0xFF
        return buf

    def write(self, buf: bytes | bytearray) -> None:
        buf = bytearray(buf)
        if len(buf) != REPORT_SIZE:
            buf = buf.ljust(REPORT_SIZE, b"\0")[:REPORT_SIZE]
        try:
            fcntl.ioctl(self.fd, HIDIOCSFEATURE(REPORT_SIZE), buf)
        except OSError as e:
            raise MouseError(f"Fareye yazılamadı: {e}") from e

    def read(self) -> bytes:
        buf = bytearray(REPORT_SIZE)
        buf[0] = REPORT_ID
        try:
            fcntl.ioctl(self.fd, HIDIOCGFEATURE(REPORT_SIZE), buf)
        except OSError as e:
            raise MouseError(f"Fareden okunamadı: {e}") from e
        return bytes(buf)

    def query(self, buf: bytes | bytearray) -> bytes:
        self.write(buf)
        return self.read()

    # --- komutlar ----------------------------------------------------------

    def device_info(self) -> bytes:
        return self.query(self._packet(OP_DEVICE_INFO))

    def device_info_2(self) -> bytes:
        return self.query(self._packet(OP_DEVICE_INFO_2))

    def composite_id(self) -> int:
        r1 = self.device_info()
        r2 = self.device_info_2()
        dev = r1[24] + (r1[9] << 8)
        dev += (r2[10] & 0xFC) << 16
        return dev

    def firmware_id(self) -> int:
        """0x05 yanıtındaki tersine çevrilmiş fare kimliği."""
        r = self.device_info()
        return int.from_bytes(r[28:32], "little")

    def get_backlight(self) -> int:
        r = self.query(self._packet(OP_BACKLIGHT, {4: 0x00}))
        return r[8]

    def set_backlight(self, level: int) -> None:
        if not 0 <= level <= 3:
            raise ValueError("Işık seviyesi 0-3 arası olmalı")
        self.write(self._packet(OP_BACKLIGHT, {4: 0x80, 8: level}))

    def set_wheel(self, enabled: bool) -> None:
        self.write(self._packet(OP_WHEEL, {8: 0 if enabled else 1}))

    def set_sensitivity(
        self, x: int, y: int, power: int, rate_hz: int, slot: int = 0, slots: int = 1
    ) -> None:
        """Etkin DPI ve rapor hızını ayarlar (geçici; fare çıkarılınca sıfırlanır).

        x, y, power: sensöre özgü ham değerler (bkz. sensor.py)
        slot: seçili DPI kademesi, slots: toplam kademe sayısı
        """
        if rate_hz not in RATE_TO_BYTE:
            raise ValueError(f"Desteklenmeyen hız: {rate_hz}")
        self.write(
            self._packet(
                OP_SENSITIVITY,
                {
                    8: max(0, slots - 1),
                    9: slot,
                    10: x,
                    11: y,
                    12: power,
                    13: RATE_TO_BYTE[rate_hz],
                },
            )
        )

    def read_memory(self, addr_hi: int, addr_lo: int, length: int = 0x60) -> bytes:
        """Kalıcı bellekten (flash) okuma. Yalnızca okur."""
        return self.query(self._packet(OP_MEMORY, {2: 0, 3: addr_hi, 4: addr_lo, 5: length}))


def hexdump(b: bytes) -> str:
    return " ".join(f"{x:02x}" for x in b)
