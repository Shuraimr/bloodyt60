#!/usr/bin/python3
"""libinput tıklama kaybı testi.

Fareyi kendi libinput örneğiyle (sistemdeki quirk dosyalarını yükleyerek) açar
ve fareden gelen ham sol tıklamaları, libinput'un ilettiği tıklamalarla
karşılaştırır. Masaüstü (niri) de tıklamaları libinput üzerinden alır.

Ctrl+C ile çık.
"""

import ctypes
import os
import select
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bloodyt60.debounce import BTN_LEFT, EV_KEY, EVENT_FMT, EVENT_SIZE, find_mouse_event_device  # noqa: E402

LI = ctypes.CDLL("libinput.so.10")
LIBC = ctypes.CDLL(None, use_errno=True)

OPEN_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
CLOSE_CB = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_void_p)


class Interface(ctypes.Structure):
    _fields_ = [("open_restricted", OPEN_CB), ("close_restricted", CLOSE_CB)]


@OPEN_CB
def _open(path, flags, _data):
    try:
        return os.open(path.decode(), flags)
    except OSError as e:
        return -e.errno


@CLOSE_CB
def _close(fd, _data):
    os.close(fd)


IFACE = Interface(_open, _close)

for name, res, args in (
    ("libinput_path_create_context", ctypes.c_void_p, [ctypes.POINTER(Interface), ctypes.c_void_p]),
    ("libinput_path_add_device", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_char_p]),
    ("libinput_get_fd", ctypes.c_int, [ctypes.c_void_p]),
    ("libinput_dispatch", ctypes.c_int, [ctypes.c_void_p]),
    ("libinput_get_event", ctypes.c_void_p, [ctypes.c_void_p]),
    ("libinput_event_get_type", ctypes.c_int, [ctypes.c_void_p]),
    ("libinput_event_get_pointer_event", ctypes.c_void_p, [ctypes.c_void_p]),
    ("libinput_event_pointer_get_button", ctypes.c_uint32, [ctypes.c_void_p]),
    ("libinput_event_pointer_get_button_state", ctypes.c_int, [ctypes.c_void_p]),
    ("libinput_event_destroy", None, [ctypes.c_void_p]),
    ("libinput_unref", ctypes.c_void_p, [ctypes.c_void_p]),
):
    fn = getattr(LI, name)
    fn.restype = res
    fn.argtypes = args

POINTER_BUTTON = 402


def main() -> int:
    path = find_mouse_event_device()
    if not path:
        print("Farenin olay cihazı bulunamadı")
        return 1
    li = LI.libinput_path_create_context(ctypes.byref(IFACE), None)
    if not LI.libinput_path_add_device(li, path.encode()):
        print(f"libinput {path} cihazını açamadı")
        return 1
    lfd = LI.libinput_get_fd(li)
    rfd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)

    raw_t: list[float] = []
    li_t: list[float] = []
    raw_total = li_total = 0
    buf = b""
    last = 0.0
    print(__doc__)
    print(f"cihaz: {path}\n")
    try:
        while True:
            r, _, _ = select.select([rfd, lfd], [], [], 0.2)
            now = time.time()
            if rfd in r:
                buf += os.read(rfd, EVENT_SIZE * 128)
                while len(buf) >= EVENT_SIZE:
                    _s, _u, typ, code, val = struct.unpack(EVENT_FMT, buf[:EVENT_SIZE])
                    buf = buf[EVENT_SIZE:]
                    if typ == EV_KEY and code == BTN_LEFT and val == 1:
                        raw_total += 1
                        raw_t.append(now)
            if lfd in r:
                LI.libinput_dispatch(li)
                while True:
                    ev = LI.libinput_get_event(li)
                    if not ev:
                        break
                    if LI.libinput_event_get_type(ev) == POINTER_BUTTON:
                        pev = LI.libinput_event_get_pointer_event(ev)
                        if (LI.libinput_event_pointer_get_button(pev) == BTN_LEFT
                                and LI.libinput_event_pointer_get_button_state(pev) == 1):
                            li_total += 1
                            li_t.append(now)
                    LI.libinput_event_destroy(ev)
            if now - last > 0.25:
                last = now
                raw_t = [t for t in raw_t if t > now - 1]
                li_t = [t for t in li_t if t > now - 1]
                lost = (raw_total - li_total) * 100 // raw_total if raw_total else 0
                sys.stdout.write(
                    f"\rham {len(raw_t):3d} CPS ({raw_total:5d}) | libinput {len(li_t):3d} CPS ({li_total:5d}) | kayıp %{max(lost, 0):3d} "
                )
                sys.stdout.flush()
    except KeyboardInterrupt:
        print()
    finally:
        os.close(rfd)
        LI.libinput_unref(li)
    return 0


if __name__ == "__main__":
    sys.exit(main())
