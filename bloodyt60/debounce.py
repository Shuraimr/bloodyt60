"""Yazılımsal tıklama debounce filtresi.

Farenin olay cihazını (evdev) özel olarak yakalar (EVIOCGRAB) ve aynı
yeteneklere sahip sanal bir fare (uinput) üzerinden olayları yeniden yayar.

Algoritma: Basma olayları anında iletilir (sıfır gecikme). Bırakma olayı
`window_ms` kadar bekletilir; bu süre içinde aynı tuşa yeniden basılırsa
hem bekleyen bırakma hem de yeni basma yutulur (çift tıklama arızası/
"chatter" giderilir). Hareket ve tekerlek olayları hiç bekletilmez.

Ek olarak `min_click_ms` ayarı ile art arda iki gerçek tıklama arasındaki
en kısa süre sınırlandırılabilir.
"""

from __future__ import annotations

import ctypes
import fcntl
import glob
import os
import select
import struct
import time

from .protocol import A4TECH_VID

# --- sabitler --------------------------------------------------------------

EV_SYN, EV_KEY, EV_REL, EV_MSC = 0x00, 0x01, 0x02, 0x04
SYN_REPORT = 0
BTN_MISC, BTN_MOUSE, BTN_LEFT, BTN_RIGHT, BTN_TASK = 0x100, 0x110, 0x110, 0x111, 0x117
KEY_MAX, REL_MAX = 0x2FF, 0x0F

EVENT_FMT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)

_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2


def _ioc(d, t, nr, size):
    return (d << 30) | (size << 16) | (ord(t) << 8) | nr


def EVIOCGBIT(ev, length):
    return _ioc(_IOC_READ, "E", 0x20 + ev, length)


EVIOCGRAB = _ioc(_IOC_WRITE, "E", 0x90, 4)
EVIOCGID = _ioc(_IOC_READ, "E", 0x02, 8)
UI_SET_EVBIT = _ioc(_IOC_WRITE, "U", 100, 4)
UI_SET_KEYBIT = _ioc(_IOC_WRITE, "U", 101, 4)
UI_SET_RELBIT = _ioc(_IOC_WRITE, "U", 102, 4)
UI_SET_MSCBIT = _ioc(_IOC_WRITE, "U", 104, 4)
UI_DEV_SETUP = _ioc(_IOC_WRITE, "U", 3, 92)
UI_DEV_CREATE = _ioc(_IOC_NONE, "U", 1, 0)
UI_DEV_DESTROY = _ioc(_IOC_NONE, "U", 2, 0)

VIRTUAL_NAME = b"Bloody T60 (bloodyt60 debounce)"


def _bits(fd: int, ev: int, maxcode: int) -> list[int]:
    nbytes = maxcode // 8 + 1
    buf = bytearray(nbytes)
    fcntl.ioctl(fd, EVIOCGBIT(ev, nbytes), buf)
    return [i for i in range(maxcode + 1) if buf[i // 8] & (1 << (i % 8))]


def find_mouse_event_device() -> str | None:
    """Fare arayüzüne ait /dev/input/eventN düğümünü bulur."""
    for sysdir in sorted(glob.glob("/sys/class/input/event*")):
        dev = os.path.join(sysdir, "device")
        try:
            vid = int(open(os.path.join(dev, "id", "vendor")).read(), 16)
            name = open(os.path.join(dev, "name")).read().strip()
            rel = open(os.path.join(dev, "capabilities", "rel")).read().split()
            key = open(os.path.join(dev, "capabilities", "key")).read().split()
        except (OSError, ValueError):
            continue
        if vid != A4TECH_VID or name.encode() == VIRTUAL_NAME:
            continue
        # REL_X|REL_Y ve BTN_LEFT bulunan cihaz = fare
        rel_bits = int(rel[-1], 16) if rel else 0
        has_left = False
        # key bitmap: boşlukla ayrılmış 64 bit kelimeler, en anlamlısı solda
        words = [int(w, 16) for w in reversed(key)]
        word, bit = divmod(BTN_LEFT, 64)
        if len(words) > word and words[word] & (1 << bit):
            has_left = True
        if rel_bits & 0b11 and has_left:
            return "/dev/input/" + os.path.basename(sysdir)
    return None


def find_meter_device() -> str | None:
    """Hız ölçümü için okunabilecek cihaz: debounce açıksa sanal fare."""
    for sysdir in sorted(glob.glob("/sys/class/input/event*")):
        try:
            name = open(os.path.join(sysdir, "device", "name")).read().strip()
        except OSError:
            continue
        if name.encode() == VIRTUAL_NAME:
            return "/dev/input/" + os.path.basename(sysdir)
    return find_mouse_event_device()


class _UinputSetup(ctypes.Structure):
    _fields_ = [
        ("bustype", ctypes.c_uint16),
        ("vendor", ctypes.c_uint16),
        ("product", ctypes.c_uint16),
        ("version", ctypes.c_uint16),
        ("name", ctypes.c_char * 80),
        ("ff_effects_max", ctypes.c_uint32),
    ]


class DebounceFilter:
    def __init__(self, event_path: str, window_ms: int = 0, min_click_ms: int = 0):
        self.event_path = event_path
        self.window = window_ms / 1000.0
        self.min_click = min_click_ms / 1000.0
        self.src = os.open(event_path, os.O_RDONLY | os.O_NONBLOCK)
        self.dst = -1
        self.pending_release: dict[int, float] = {}  # tuş -> son tarih
        self.swallow_release: set[int] = set()
        self.last_press: dict[int, float] = {}
        self.stats = {"chatter": 0, "rate_limited": 0}
        self._create_virtual()
        fcntl.ioctl(self.src, EVIOCGRAB, 1)

    def set_params(self, window_ms: int, min_click_ms: int) -> None:
        self.window = window_ms / 1000.0
        self.min_click = min_click_ms / 1000.0

    def _create_virtual(self) -> None:
        self.dst = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.dst, UI_SET_EVBIT, EV_SYN)
        for ev, maxc, setter in (
            (EV_KEY, KEY_MAX, UI_SET_KEYBIT),
            (EV_REL, REL_MAX, UI_SET_RELBIT),
            (EV_MSC, 0x07, UI_SET_MSCBIT),
        ):
            codes = _bits(self.src, ev, maxc)
            if codes:
                fcntl.ioctl(self.dst, UI_SET_EVBIT, ev)
                for c in codes:
                    fcntl.ioctl(self.dst, setter, c)
        idbuf = bytearray(8)
        fcntl.ioctl(self.src, EVIOCGID, idbuf)
        bus, vendor, product, version = struct.unpack("HHHH", idbuf)
        setup = _UinputSetup(0x06, vendor, product, version, VIRTUAL_NAME, 0)
        fcntl.ioctl(self.dst, UI_DEV_SETUP, bytes(setup))
        fcntl.ioctl(self.dst, UI_DEV_CREATE)

    def _emit(self, typ: int, code: int, value: int) -> None:
        now = time.time()
        sec = int(now)
        os.write(self.dst, struct.pack(EVENT_FMT, sec, int((now - sec) * 1e6), typ, code, value))

    def _emit_key(self, code: int, value: int) -> None:
        self._emit(EV_KEY, code, value)
        self._emit(EV_SYN, SYN_REPORT, 0)

    @staticmethod
    def _is_button(code: int) -> bool:
        return BTN_MISC <= code < 0x160

    def _flush_due(self, now: float) -> None:
        for code, due in list(self.pending_release.items()):
            if now >= due:
                del self.pending_release[code]
                self._emit_key(code, 0)

    def _next_timeout(self, now: float) -> float | None:
        if not self.pending_release:
            return None
        return max(0.0, min(self.pending_release.values()) - now)

    def _handle(self, typ: int, code: int, value: int) -> bool:
        """True dönerse olay iletilir."""
        if typ != EV_KEY or not self._is_button(code):
            return True
        now = time.monotonic()
        if value == 1:  # basma
            if code in self.pending_release:
                # Bırakmadan hemen sonra gelen basma -> arıza. İkisini de yut.
                del self.pending_release[code]
                self.stats["chatter"] += 1
                return False
            last = self.last_press.get(code)
            if self.min_click and last is not None and now - last < self.min_click:
                self.swallow_release.add(code)
                self.stats["rate_limited"] += 1
                return False
            self.last_press[code] = now
            return True
        if value == 0:  # bırakma
            if code in self.swallow_release:
                self.swallow_release.discard(code)
                return False
            if self.window > 0:
                self.pending_release[code] = now + self.window
                return False
            return True
        return True

    def run(self, stop_fd: int | None = None) -> None:
        """Ana döngü. stop_fd okunabilir olduğunda veya cihaz gidince döner."""
        fds = [self.src] + ([stop_fd] if stop_fd is not None else [])
        buf = b""
        held_syn = False
        try:
            while True:
                now = time.monotonic()
                self._flush_due(now)
                r, _, _ = select.select(fds, [], [], self._next_timeout(time.monotonic()))
                if stop_fd is not None and stop_fd in r:
                    return
                if self.src not in r:
                    continue
                try:
                    data = os.read(self.src, EVENT_SIZE * 64)
                except BlockingIOError:
                    continue
                except OSError:
                    return  # cihaz çıkarıldı
                if not data:
                    return
                buf += data
                while len(buf) >= EVENT_SIZE:
                    _s, _u, typ, code, value = struct.unpack(EVENT_FMT, buf[:EVENT_SIZE])
                    buf = buf[EVENT_SIZE:]
                    if typ == EV_SYN:
                        if held_syn:
                            self._emit(typ, code, value)
                            held_syn = False
                        continue
                    if self._handle(typ, code, value):
                        self._emit(typ, code, value)
                        held_syn = True
        finally:
            self.close()

    def close(self) -> None:
        # Bekleyen bırakmaları gönder ki tuş basılı kalmasın.
        if self.dst >= 0:
            for code in list(self.pending_release):
                try:
                    self._emit_key(code, 0)
                except OSError:
                    pass
            self.pending_release.clear()
            try:
                fcntl.ioctl(self.dst, UI_DEV_DESTROY)
            except OSError:
                pass
            os.close(self.dst)
            self.dst = -1
        if self.src >= 0:
            try:
                fcntl.ioctl(self.src, EVIOCGRAB, 0)
            except OSError:
                pass
            os.close(self.src)
            self.src = -1
