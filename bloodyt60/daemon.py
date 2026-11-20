"""Arka plan servisi.

- Fare takıldığında ayarları uygular (DPI/Hz fare belleğinde kalıcı değildir).
- Ayar dosyası değişince yeniden uygular.
- Farenin DPI tuşunu dinleyip sıradaki DPI kademesine geçer.
- Yazılımsal debounce filtresini çalıştırır.
"""

from __future__ import annotations

import logging
import os
import select
import threading
import time

from . import sensor
from .apply import apply_config, mouse_sensor
from .config import Config
from .debounce import DebounceFilter, find_mouse_event_device
from .protocol import REPORT_ID, BloodyMouse, MouseError, find_devices

log = logging.getLogger("bloodyt60")

# Fare DPI tuşuna basıldığında 0x07 raporunun bu baytı kademe numarasını taşır.
DPI_EVENT_OPCODE = 0x01
DPI_EVENT_SLOT_INDEX = 12


class DebounceThread:
    def __init__(self, window_ms: int, min_click_ms: int):
        self.r, self.w = os.pipe()
        path = find_mouse_event_device()
        if path is None:
            raise MouseError("Farenin olay cihazı bulunamadı")
        self.filter = DebounceFilter(path, window_ms, min_click_ms)
        self.thread = threading.Thread(target=self.filter.run, args=(self.r,), daemon=True)
        self.thread.start()
        log.info("debounce etkin: %s (%d ms, min %d ms)", path, window_ms, min_click_ms)

    def alive(self) -> bool:
        return self.thread.is_alive()

    def stop(self) -> None:
        os.write(self.w, b"x")
        self.thread.join(2)
        os.close(self.r)
        os.close(self.w)


class Daemon:
    def __init__(self):
        self.mouse: BloodyMouse | None = None
        self.info: sensor.SensorInfo | None = None
        self.cfg = Config.load()
        self.cfg_mtime = Config.mtime()
        self.debounce: DebounceThread | None = None

    def connect(self) -> None:
        devs = find_devices()
        if not devs:
            return
        try:
            self.mouse = BloodyMouse(devs[0])
            self.info = mouse_sensor(self.mouse)
            log.info("fare bağlandı: %s (%s)", devs[0].name, self.info and self.info.label)
            # Fare yeni takıldıysa firmware'in hazır olması için kısa bekleme
            time.sleep(0.3)
            self.apply()
        except MouseError as e:
            log.warning("%s", e)
            self.disconnect()

    def disconnect(self) -> None:
        self.stop_debounce()
        if self.mouse:
            self.mouse.close()
        self.mouse = None

    def apply(self) -> None:
        if not self.mouse:
            return
        for w in apply_config(self.mouse, self.cfg, self.info):
            log.warning(w)
        log.info(
            "uygulandı: %d DPI, %d Hz, ışık %d",
            self.cfg.dpi_slots[self.cfg.active_slot], self.cfg.rate_hz, self.cfg.backlight,
        )
        self.sync_debounce()

    def sync_debounce(self) -> None:
        want = self.cfg.debounce_enabled and (self.cfg.debounce_ms > 0 or self.cfg.min_click_ms > 0)
        if self.debounce and not self.debounce.alive():
            self.stop_debounce()
        if want and self.debounce is None:
            try:
                self.debounce = DebounceThread(self.cfg.debounce_ms, self.cfg.min_click_ms)
            except (OSError, MouseError) as e:
                log.warning("debounce başlatılamadı: %s", e)
        elif want and self.debounce:
            self.debounce.filter.set_params(self.cfg.debounce_ms, self.cfg.min_click_ms)
        elif not want:
            self.stop_debounce()

    def stop_debounce(self) -> None:
        if self.debounce:
            self.debounce.stop()
            self.debounce = None

    def on_report(self, data: bytes) -> None:
        if len(data) <= DPI_EVENT_SLOT_INDEX or data[0] != REPORT_ID or data[1] != DPI_EVENT_OPCODE:
            return
        slot = data[DPI_EVENT_SLOT_INDEX]
        n = len(self.cfg.dpi_slots)
        if slot >= 0x80 or n == 0:
            return
        slot %= n
        if slot != self.cfg.active_slot:
            self.cfg.active_slot = slot
            self.cfg.save()
            self.cfg_mtime = Config.mtime()
            log.info("DPI tuşu: kademe %d", slot + 1)
            self.apply()

    def run(self) -> None:
        from .service import acquire_daemon_lock

        self._lock = acquire_daemon_lock()
        if self._lock is None:
            log.info("bloodyt60 servisi zaten çalışıyor, çıkılıyor")
            return
        log.info("bloodyt60 servisi başladı")
        while True:
            if self.mouse is None:
                self.connect()
                if self.mouse is None:
                    time.sleep(1.5)
                    continue
            mt = Config.mtime()
            if mt != self.cfg_mtime:
                self.cfg_mtime = mt
                self.cfg = Config.load()
                try:
                    self.apply()
                except MouseError as e:
                    log.warning("%s", e)
                    self.disconnect()
                    continue
            if self.debounce and not self.debounce.alive():
                self.sync_debounce()
            try:
                r, _, _ = select.select([self.mouse.fd], [], [], 0.5)
                if r:
                    self.on_report(os.read(self.mouse.fd, 64))
            except OSError:
                log.info("fare çıkarıldı")
                self.disconnect()
