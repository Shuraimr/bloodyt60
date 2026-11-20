#!/usr/bin/python3
"""X11 (Xwayland) tıklama kaybını otomatik ölçer.

Sanal bir fare (uinput) ile test penceresine bilinen sayıda, bilinen hızda
tıklama gönderir ve X11 penceresine kaçının ulaştığını sayar. Pencere tam
ekran ve odakta değilse tıklama göndermez.
"""

import ctypes
import fcntl
import json
import os
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bloodyt60.debounce import (  # noqa: E402
    BTN_LEFT, EV_KEY, EV_REL, EV_SYN, EVENT_FMT, UI_DEV_CREATE, UI_DEV_DESTROY, UI_DEV_SETUP,
    UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT, _UinputSetup,
)

TITLE = b"bloodyt60 X11 auto test"
X = ctypes.CDLL("libX11.so.6")
X.XInitThreads()
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
X.XGrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint, ctypes.c_int,
                           ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
X.XUngrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
X.XDestroyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
X.XCloseDisplay.argtypes = [ctypes.c_void_p]

MASK = 1 | 4 | 8 | 64 | 32768 | 16 | 32  # + EnterWindow, LeaveWindow


class XWMHints(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_long), ("input", ctypes.c_int), ("initial_state", ctypes.c_int),
                ("icon_pixmap", ctypes.c_ulong), ("icon_window", ctypes.c_ulong), ("icon_x", ctypes.c_int),
                ("icon_y", ctypes.c_int), ("icon_mask", ctypes.c_ulong), ("window_group", ctypes.c_ulong)]


X.XSetWMHints.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XWMHints)]  # Key, ButtonPress, ButtonRelease, PointerMotion, Exposure


def niri(*args):
    return subprocess.run(["niri", "msg", *args], capture_output=True, text=True).stdout


def focused_title() -> str:
    try:
        return (json.loads(niri("--json", "focused-window")) or {}).get("title", "")
    except ValueError:
        return ""


class VMouse:
    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_KEYBIT, BTN_LEFT)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
        fcntl.ioctl(self.fd, UI_SET_RELBIT, 0)
        fcntl.ioctl(self.fd, UI_SET_RELBIT, 1)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, bytes(_UinputSetup(0x03, 0x1234, 0x5678, 1, b"bloodyt60 test mouse", 0)))
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.8)  # kompozitör cihazı görsün

    def emit(self, typ, code, val):
        now = time.time()
        os.write(self.fd, struct.pack(EVENT_FMT, int(now), int((now % 1) * 1e6), typ, code, val))

    def move(self, dx, dy):
        self.emit(EV_REL, 0, dx)
        self.emit(EV_REL, 1, dy)
        self.emit(EV_SYN, 0, 0)

    def button(self, down):
        self.emit(EV_KEY, BTN_LEFT, 1 if down else 0)
        self.emit(EV_SYN, 0, 0)

    def close(self):
        fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        os.close(self.fd)


def main() -> int:
    dpy = X.XOpenDisplay(None)
    root = X.XDefaultRootWindow(dpy)
    win = X.XCreateSimpleWindow(dpy, root, 0, 0, 800, 600, 0, 0, 0x301018)
    X.XStoreName(dpy, win, TITLE)
    X.XSelectInput(dpy, win, MASK)
    hints = XWMHints(flags=1 | 2, input=1, initial_state=1)
    X.XSetWMHints(dpy, win, ctypes.byref(hints))
    X.XMapWindow(dpy, win)
    X.XFlush(dpy)

    counts = {}
    presses = [0]
    stop = [False]
    lock = threading.Lock()

    def pump():
        ev = ctypes.create_string_buffer(192)
        while not stop[0]:
            with lock:
                while X.XPending(dpy):
                    X.XNextEvent(dpy, ev)
                    t = struct.unpack_from("i", ev.raw, 0)[0]
                    counts[t] = counts.get(t, 0) + 1
                    if t == 4 and struct.unpack_from("I", ev.raw, 84)[0] == 1:
                        presses[0] += 1
            time.sleep(0.001)

    th = threading.Thread(target=pump, daemon=True)
    th.start()
    time.sleep(1.0)

    wins = json.loads(niri("--json", "windows"))
    wid = next((w["id"] for w in wins if w.get("title") == TITLE.decode()), None)
    if wid is None:
        print("test penceresi niri'de bulunamadı")
        return 1
    niri("action", "focus-window", "--id", str(wid))
    time.sleep(0.3)
    niri("action", "fullscreen-window", "--id", str(wid))
    time.sleep(1.0)

    vm = VMouse()
    results = []
    try:
        vm.move(5, 5)
        time.sleep(0.2)

        def burst(label, n, down_ms, up_ms, grab=False):
            if focused_title() != TITLE.decode():
                print(f"{label}: ATLANDI (test penceresi odakta değil)")
                return
            if grab:
                with lock:
                    X.XGrabPointer(dpy, win, 1, 4 | 8 | 64, 1, 1, win, 0, 0)
                    X.XFlush(dpy)
                time.sleep(0.3)
            time.sleep(0.3)
            presses[0] = 0
            for _ in range(n):
                vm.button(True)
                time.sleep(down_ms / 1000)
                vm.button(False)
                time.sleep(up_ms / 1000)
            time.sleep(0.5)
            got = presses[0]
            if grab:
                with lock:
                    X.XUngrabPointer(dpy, 0)
                    X.XFlush(dpy)
                time.sleep(0.2)
            cps = 1000 / (down_ms + up_ms)
            results.append((label, n, got))
            print(f"{label:34s} gönderilen {n:4d}  ulaşan {got:4d}  (~{cps:.0f} CPS)", flush=True)

        burst("yavaş 10 CPS", 30, 30, 70)
        vm.move(40, 40)
        burst("hızlı 25 CPS", 60, 15, 25)
        burst("drag 60 CPS", 120, 5, 11)
        burst("drag 60 CPS, 1ms basılı", 120, 1, 15)
        burst("kilitli: yavaş 10 CPS", 30, 30, 70, grab=True)
        burst("kilitli: drag 60 CPS", 120, 5, 11, grab=True)
        print("X olay türleri:", dict(sorted(counts.items())))
    finally:
        vm.close()
        stop[0] = True
        th.join(1)
        X.XDestroyWindow(dpy, win)
        X.XFlush(dpy)
    return 0


if __name__ == "__main__":
    sys.exit(main())
