"""bloodyt60 komut satırı.

    python3 -m bloodyt60 gui            grafik arayüz
    python3 -m bloodyt60 info           fare bilgisi
    python3 -m bloodyt60 apply          kayıtlı ayarları uygula
    python3 -m bloodyt60 set --ms 1 --dpi 1600 --light 2
    python3 -m bloodyt60 measure        gerçek rapor hızını ölç (fareyi oynat)
    python3 -m bloodyt60 daemon         arka plan servisi
"""

from __future__ import annotations

import argparse
import logging
import os
import select
import statistics
import struct
import sys
import time


def cmd_info(_a) -> int:
    from .apply import mouse_sensor
    from .protocol import BloodyMouse

    with BloodyMouse.open_first() as m:
        info = mouse_sensor(m)
        print(f"Cihaz     : {m.info.name} ({m.info.vid:04x}:{m.info.pid:04x}) {m.info.path}")
        print(f"Kimlik    : {m.composite_id():#x}")
        print(f"Sensör    : {info.label if info else 'bilinmiyor'}"
              f"{f', en fazla {info.max_cpi} DPI' if info else ''}")
        print(f"Işık      : {m.get_backlight()}")
    return 0


def cmd_apply(_a) -> int:
    from .apply import apply_config
    from .config import Config
    from .protocol import BloodyMouse

    with BloodyMouse.open_first() as m:
        for w in apply_config(m, Config.load()):
            print("uyarı:", w)
    print("Ayarlar uygulandı.")
    return 0


def cmd_set(a) -> int:
    from .config import Config

    cfg = Config.load()
    if a.hz:
        cfg.rate_hz = a.hz
    if a.ms:
        cfg.rate_hz = 1000 // a.ms
    if a.dpi:
        cfg.dpi_slots[cfg.active_slot] = a.dpi
    if a.light is not None:
        cfg.backlight = a.light
    if a.debounce is not None:
        cfg.debounce_ms = a.debounce
        cfg.debounce_enabled = a.debounce > 0
    cfg.save()
    return cmd_apply(a)


def measure_rate(seconds: float = 3.0, path: str | None = None) -> tuple[float, int] | None:
    """Fare hareket ederken ardışık raporlar arasındaki aralıktan Hz hesaplar."""
    from .debounce import EV_REL, EV_SYN, EVENT_FMT, EVENT_SIZE, find_mouse_event_device

    path = path or find_mouse_event_device()
    if not path:
        return None
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    stamps: list[float] = []
    saw_rel = False
    end = time.monotonic() + seconds
    buf = b""
    try:
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if not r:
                continue
            buf += os.read(fd, EVENT_SIZE * 128)
            while len(buf) >= EVENT_SIZE:
                s, us, typ, _code, _v = struct.unpack(EVENT_FMT, buf[:EVENT_SIZE])
                buf = buf[EVENT_SIZE:]
                if typ == EV_REL:
                    saw_rel = True
                elif typ == EV_SYN and saw_rel:
                    stamps.append(s + us / 1e6)
                    saw_rel = False
    finally:
        os.close(fd)
    gaps = [b - a for a, b in zip(stamps, stamps[1:]) if 0 < b - a < 0.02]
    if len(gaps) < 20:
        return None
    return 1.0 / statistics.median(gaps), len(stamps)


def cmd_measure(a) -> int:
    print(f"{a.seconds:.0f} saniye boyunca fareyi sürekli hızlıca daireler çizerek oynat...")
    res = measure_rate(a.seconds)
    if res is None:
        print("Yeterli hareket ölçülemedi.")
        return 1
    hz, n = res
    print(f"Ölçülen rapor hızı: ~{hz:.0f} Hz ({n} rapor)")
    return 0


def cmd_daemon(_a) -> int:
    from .daemon import Daemon

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    Daemon().run()
    return 0


def cmd_gui(_a) -> int:
    from .gui import main

    return main()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="bloodyt60", description="Bloody T60 Linux yapılandırıcı")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("gui")
    sub.add_parser("info")
    sub.add_parser("apply")
    sub.add_parser("daemon")
    sp = sub.add_parser("set")
    sp.add_argument("--hz", type=int, choices=[125, 250, 500, 1000])
    sp.add_argument("--ms", type=int, choices=[1, 2, 4, 8], help="polling aralığı (1 ms = 1000 Hz)")
    sp.add_argument("--dpi", type=int)
    sp.add_argument("--light", type=int, choices=[0, 1, 2, 3])
    sp.add_argument("--debounce", type=int, help="ms, 0 = kapalı")
    mp = sub.add_parser("measure")
    mp.add_argument("--seconds", type=float, default=4.0)
    a = p.parse_args(argv)
    handlers = {
        "info": cmd_info, "apply": cmd_apply, "set": cmd_set, "measure": cmd_measure,
        "daemon": cmd_daemon, "gui": cmd_gui, None: cmd_gui,
    }
    from .protocol import MouseError

    try:
        return handlers[a.cmd](a)
    except MouseError as e:
        print("Hata:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
