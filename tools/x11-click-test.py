#!/usr/bin/python3
"""X11 (Xwayland) üzerinden tıklama kaybı testi.

Minecraft 1.8.9 / LWJGL2 gibi X11 oyunlarının gördüğü tıklamaları, fareden
gelen ham tıklamalarla karşılaştırır. Pencerenin içine tıkla / drag click yap.

    g    : imleci kilitle/bırak (oyun içindeki gibi pointer grab)
    r    : sayaçları sıfırla
    Esc  : çık
"""

import ctypes
import os
import select
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bloodyt60.debounce import BTN_LEFT, EV_KEY, EVENT_FMT, EVENT_SIZE, find_mouse_event_device  # noqa: E402

X = ctypes.CDLL("libX11.so.6")
X.XOpenDisplay.restype = ctypes.c_void_p
X.XOpenDisplay.argtypes = [ctypes.c_char_p]
X.XDefaultRootWindow.restype = ctypes.c_ulong
X.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
X.XCreateSimpleWindow.restype = ctypes.c_ulong
X.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong]
X.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
X.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
X.XStoreName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p]
X.XPending.argtypes = [ctypes.c_void_p]
X.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
X.XFlush.argtypes = [ctypes.c_void_p]
X.XConnectionNumber.argtypes = [ctypes.c_void_p]
X.XLookupKeysym.restype = ctypes.c_ulong
X.XLookupKeysym.argtypes = [ctypes.c_void_p, ctypes.c_int]
X.XGrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint, ctypes.c_int,
                           ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
X.XUngrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

KeyPress, ButtonPress = 2, 4
KeyPressMask, ButtonPressMask, ButtonReleaseMask, PointerMotionMask, ExposureMask = 1, 4, 8, 64, 32768


def main() -> int:
    dpy = X.XOpenDisplay(None)
    if not dpy:
        print("X ekranına bağlanılamadı (DISPLAY?)")
        return 1
    root = X.XDefaultRootWindow(dpy)
    win = X.XCreateSimpleWindow(dpy, root, 0, 0, 640, 400, 0, 0, 0x202024)
    X.XStoreName(dpy, win, b"bloodyt60 X11 click test")
    X.XSelectInput(dpy, win, KeyPressMask | ButtonPressMask | ButtonReleaseMask | ExposureMask)
    X.XMapWindow(dpy, win)
    X.XFlush(dpy)

    path = find_mouse_event_device()
    if not path:
        print("Farenin olay cihazı bulunamadı")
        return 1
    efd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    xfd = X.XConnectionNumber(dpy)
    ev = ctypes.create_string_buffer(192)

    raw = x11 = 0
    raw_t: list[float] = []
    x11_t: list[float] = []
    grabbed = False
    buf = b""
    last_print = 0.0
    print(__doc__)
    try:
        while True:
            r, _, _ = select.select([efd, xfd], [], [], 0.25)
            if efd in r:
                buf += os.read(efd, EVENT_SIZE * 128)
                while len(buf) >= EVENT_SIZE:
                    _s, _u, typ, code, val = struct.unpack(EVENT_FMT, buf[:EVENT_SIZE])
                    buf = buf[EVENT_SIZE:]
                    if typ == EV_KEY and code == BTN_LEFT and val == 1:
                        raw += 1
                        raw_t.append(time.time())
            while X.XPending(dpy):
                X.XNextEvent(dpy, ev)
                etype = struct.unpack_from("i", ev.raw, 0)[0]
                if etype == ButtonPress:
                    button = struct.unpack_from("I", ev.raw, 84)[0]
                    if button == 1:
                        x11 += 1
                        x11_t.append(time.time())
                elif etype == KeyPress:
                    sym = X.XLookupKeysym(ev, 0)
                    if sym == 0xFF1B:
                        return 0
                    if sym == ord("r"):
                        raw = x11 = 0
                        raw_t.clear()
                        x11_t.clear()
                    if sym == ord("g"):
                        if grabbed:
                            X.XUngrabPointer(dpy, 0)
                        else:
                            X.XGrabPointer(dpy, win, 1, ButtonPressMask | ButtonReleaseMask | PointerMotionMask,
                                           1, 1, win, 0, 0)
                        grabbed = not grabbed
                        X.XFlush(dpy)
            now = time.time()
            if now - last_print > 0.5:
                last_print = now
                rc = sum(1 for t in raw_t if t > now - 1)
                xc = sum(1 for t in x11_t if t > now - 1)
                lost = (raw - x11) * 100 // raw if raw else 0
                sys.stdout.write(
                    f"\rham: {raw:5d} ({rc:3d} CPS)   X11: {x11:5d} ({xc:3d} CPS)   "
                    f"kayıp: %{max(lost, 0):3d}   kilit: {'AÇIK ' if grabbed else 'kapalı'}"
                )
                sys.stdout.flush()
    finally:
        print()
        os.close(efd)


if __name__ == "__main__":
    sys.exit(main())
