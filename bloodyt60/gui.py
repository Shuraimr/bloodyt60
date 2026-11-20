"""GTK4 + libadwaita arayüzü."""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import time
from collections import deque

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import sensor  # noqa: E402
from .apply import apply_config, mouse_sensor  # noqa: E402
from .config import Config  # noqa: E402
from .debounce import BTN_LEFT, EV_KEY, EV_REL, EV_SYN, EVENT_FMT, EVENT_SIZE, find_meter_device  # noqa: E402
from .protocol import BloodyMouse, MouseError, find_devices  # noqa: E402

APP_ID = "io.github.bloodyt60"
SERVICE = "bloodyt60.service"
MAX_SLOTS = 5

CSS = """
:root {
  --accent-bg-color: #c8102e;
  --accent-color: #ff4d5e;
  --accent-fg-color: #ffffff;
}
.hero {
  border-radius: 18px;
  padding: 22px 26px;
  background: linear-gradient(135deg, alpha(#c8102e, 0.22), alpha(#c8102e, 0.04) 60%);
  border: 1px solid alpha(#c8102e, 0.35);
}
.hz-number { font-size: 54px; font-weight: 800; font-feature-settings: "tnum"; }
.hz-unit { font-size: 18px; font-weight: 700; opacity: 0.6; }
.model { font-size: 22px; font-weight: 800; letter-spacing: 1px; }
.chip {
  border-radius: 99px; padding: 2px 10px; font-size: 12px; font-weight: 700;
  background: alpha(currentColor, 0.08);
}
.chip.ok { color: #3ddc84; background: alpha(#3ddc84, 0.14); }
.chip.bad { color: #ff5a5a; background: alpha(#ff5a5a, 0.14); }
.slot-active { color: var(--accent-color); font-weight: 800; }
.sparkline { min-height: 64px; }
.cps-area {
  border-radius: 14px;
  border: 2px dashed alpha(currentColor, 0.18);
  background: alpha(currentColor, 0.03);
}
.cps-area:hover { border-color: alpha(#c8102e, 0.7); background: alpha(#c8102e, 0.06); }
.cps-value { font-size: 30px; font-weight: 800; font-feature-settings: "tnum"; }
.cps-caption { font-size: 10px; font-weight: 700; letter-spacing: 1px; opacity: 0.55; }
"""


class HzMeter:
    """Fare olay cihazından canlı rapor hızı ölçer."""

    def __init__(self, on_update):
        self.on_update = on_update
        self.on_click = None  # (zaman, tuş_kodu) çağrısı
        self.fd = -1
        self.watch = 0
        self.saw_rel = False
        self.last: float | None = None
        self.gaps: deque[float] = deque(maxlen=200)
        self.history: deque[float] = deque(maxlen=120)
        self.buf = b""
        self.last_move = 0.0
        GLib.timeout_add(250, self._tick)

    def ensure_open(self) -> None:
        if self.fd >= 0:
            return
        path = find_meter_device()
        if not path:
            return
        try:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return
        self.watch = GLib.unix_fd_add_full(
            GLib.PRIORITY_HIGH, self.fd, GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
            self._on_io,
        )

    def close(self) -> None:
        if self.watch:
            GLib.source_remove(self.watch)
            self.watch = 0
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def _on_io(self, fd, cond):
        if cond & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
            self.watch = 0
            os.close(self.fd)
            self.fd = -1
            return GLib.SOURCE_REMOVE
        try:
            self.buf += os.read(fd, EVENT_SIZE * 128)
        except BlockingIOError:
            return GLib.SOURCE_CONTINUE
        except OSError:
            self.watch = 0
            os.close(self.fd)
            self.fd = -1
            return GLib.SOURCE_REMOVE
        while len(self.buf) >= EVENT_SIZE:
            s, us, typ, _c, _v = struct.unpack(EVENT_FMT, self.buf[:EVENT_SIZE])
            self.buf = self.buf[EVENT_SIZE:]
            if typ == EV_REL:
                self.saw_rel = True
            elif typ == EV_KEY and _v == 1 and self.on_click:
                self.on_click(s + us / 1e6, _c)
            elif typ == EV_SYN and self.saw_rel:
                self.saw_rel = False
                t = s + us / 1e6
                if self.last is not None and 0 < t - self.last < 0.02:
                    self.gaps.append(t - self.last)
                self.last = t
                self.last_move = time.monotonic()
        return GLib.SOURCE_CONTINUE

    def current(self) -> float | None:
        if time.monotonic() - self.last_move > 0.4 or len(self.gaps) < 15:
            return None
        recent = sorted(list(self.gaps)[-60:])
        return 1.0 / recent[len(recent) // 2]

    def _tick(self):
        self.ensure_open()
        hz = self.current()
        if hz is None and time.monotonic() - self.last_move > 0.4:
            self.gaps.clear()
        self.history.append(hz or 0.0)
        self.on_update(hz)
        return GLib.SOURCE_CONTINUE


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Bloody T60")
        self.set_default_size(560, 860)
        self.cfg = Config.load()
        self.mouse: BloodyMouse | None = None
        self.info: sensor.SensorInfo | None = None
        self._loading = False
        self._apply_source = 0

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        reapply = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Ayarları yeniden uygula")
        reapply.connect("clicked", lambda *_: self.apply_now(toast=True))
        header.pack_start(reapply)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        page.add(self._build_hero())
        page.add(self._build_rate())
        page.add(self._build_dpi())
        page.add(self._build_cps())
        page.add(self._build_click())
        page.add(self._build_misc())
        page.add(self._build_service())
        view.set_content(page)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        self.meter = HzMeter(self._on_hz)
        self.meter.on_click = self._on_raw_click
        self.connect("close-request", self._on_close)
        self.refresh_device()
        GLib.timeout_add_seconds(2, self._poll_device)

    # --- kurulum ---------------------------------------------------------

    def _build_hero(self) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("hero")

        top = Gtk.Box(spacing=10)
        icon = Gtk.Image(icon_name="input-mouse-symbolic", pixel_size=28)
        top.append(icon)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.model_label = Gtk.Label(label="BLOODY T60", xalign=0)
        self.model_label.add_css_class("model")
        self.sub_label = Gtk.Label(label="Aranıyor…", xalign=0)
        self.sub_label.add_css_class("dim-label")
        titles.append(self.model_label)
        titles.append(self.sub_label)
        top.append(titles)
        spacer = Gtk.Box(hexpand=True)
        top.append(spacer)
        self.status_chip = Gtk.Label(label="BAĞLI DEĞİL", valign=Gtk.Align.CENTER)
        self.status_chip.add_css_class("chip")
        self.status_chip.add_css_class("bad")
        top.append(self.status_chip)
        box.append(top)

        hz_row = Gtk.Box(spacing=6)
        self.hz_label = Gtk.Label(label="—")
        self.hz_label.add_css_class("hz-number")
        unit = Gtk.Label(label="Hz", valign=Gtk.Align.END, margin_bottom=12)
        unit.add_css_class("hz-unit")
        hz_row.append(self.hz_label)
        hz_row.append(unit)
        hz_row.append(Gtk.Box(hexpand=True))
        self.hz_hint = Gtk.Label(
            label="Ölçmek için fareyi\nhızlıca oynat", justify=Gtk.Justification.RIGHT,
            valign=Gtk.Align.CENTER,
        )
        self.hz_hint.add_css_class("dim-label")
        self.hz_hint.add_css_class("caption")
        hz_row.append(self.hz_hint)
        box.append(hz_row)

        self.spark = Gtk.DrawingArea(content_height=64)
        self.spark.add_css_class("sparkline")
        self.spark.set_draw_func(self._draw_spark)
        box.append(self.spark)
        g.add(box)
        return g

    def _toggle_group(self, items: list[tuple[str, str]], active: str, cb) -> Adw.ToggleGroup:
        tg = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        tg.add_css_class("round")
        for name, label in items:
            tg.add(Adw.Toggle(name=name, label=label))
        tg.set_active_name(active)
        tg.connect("notify::active-name", lambda w, _p: cb(w.get_active_name()))
        return tg

    def _build_rate(self) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(
            title="Polling aralığı",
            description="Farenin bilgisayara ne sıklıkla rapor gönderdiği (donanım ayarı). "
            "1 ms = 1000 Hz farenin ve USB'nin en hızlı değeridir; drag click için 1 ms seç.",
        )
        row = Adw.ActionRow(title="Polling rate")
        self.rate_row = row
        self.rate_tg = self._toggle_group(
            [("1000", "1 ms"), ("500", "2 ms"), ("250", "4 ms"), ("125", "8 ms")],
            str(self.cfg.rate_hz), self._on_rate,
        )
        row.set_subtitle(f"{self.cfg.rate_hz} Hz")
        row.add_suffix(self.rate_tg)
        g.add(row)
        return g

    def _build_dpi(self) -> Adw.PreferencesGroup:
        self.dpi_group = Adw.PreferencesGroup(
            title="DPI kademeleri",
            description="Farenin DPI tuşu kademeler arasında dolaşır (servis çalışırken). "
            "Yıldızlı kademe etkin olandır.",
        )
        add = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Kademe ekle")
        add.add_css_class("flat")
        add.connect("clicked", self._on_add_slot)
        self.dpi_group.set_header_suffix(add)
        self.add_btn = add
        self.slot_rows: list[Adw.SpinRow] = []
        self._rebuild_slots()
        return self.dpi_group

    def _rebuild_slots(self) -> None:
        for r in self.slot_rows:
            self.dpi_group.remove(r)
        self.slot_rows = []
        max_cpi = self.info.max_cpi if self.info else 4000
        first_check: Gtk.CheckButton | None = None
        for i, dpi in enumerate(self.cfg.dpi_slots):
            adj = Gtk.Adjustment(lower=100, upper=max_cpi, step_increment=50, page_increment=500, value=dpi)
            row = Adw.SpinRow(title=f"Kademe {i + 1}", adjustment=adj, numeric=True)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER, tooltip_text="Etkin kademe yap")
            if first_check is None:
                first_check = check
            else:
                check.set_group(first_check)
            check.set_active(i == self.cfg.active_slot)
            check.connect("toggled", self._on_slot_select, i)
            row.add_prefix(check)
            if len(self.cfg.dpi_slots) > 1:
                rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Kaldır")
                rm.add_css_class("flat")
                rm.connect("clicked", self._on_remove_slot, i)
                row.add_suffix(rm)
            if i == self.cfg.active_slot:
                row.add_css_class("slot-active")
                row.set_subtitle("★ etkin")
            adj.connect("value-changed", self._on_dpi_changed, i)
            self.dpi_group.add(row)
            self.slot_rows.append(row)
        self.add_btn.set_sensitive(len(self.cfg.dpi_slots) < MAX_SLOTS)

    def _build_cps(self) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(
            title="CPS testi",
            description="İmleç alanın içindeyken sol tıkla (drag click dahil). Zamanlar "
            "çekirdekten alınır; 'en kısa aralık' farenin firmware debounce sınırını gösterir.",
        )
        reset = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Sıfırla")
        reset.add_css_class("flat")
        reset.connect("clicked", lambda *_: self._cps_reset())
        g.set_header_suffix(reset)

        area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, height_request=170)
        area.add_css_class("cps-area")
        area.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        row = Gtk.Box(homogeneous=True, vexpand=True, valign=Gtk.Align.CENTER)
        self.cps_now = self._stat(row, "CPS")
        self.cps_peak = self._stat(row, "EN YÜKSEK")
        self.cps_min = self._stat(row, "EN KISA ARALIK")
        self.cps_total = self._stat(row, "TOPLAM")
        area.append(row)
        self.cps_hint = Gtk.Label(label="Buraya tıklayarak başla")
        self.cps_hint.add_css_class("dim-label")
        self.cps_hint.add_css_class("caption")
        self.cps_hint.set_margin_bottom(10)
        area.append(self.cps_hint)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: setattr(self, "cps_inside", True))
        motion.connect("leave", lambda *_: setattr(self, "cps_inside", False))
        area.add_controller(motion)
        # Alan içi tıklamalar pencerenin geri kalanına yayılmasın
        click = Gtk.GestureClick(button=0)
        area.add_controller(click)
        self.cps_inside = False
        self.cps_times: deque[float] = deque(maxlen=4000)
        self.cps_best = 0
        self.cps_min_gap: float | None = None
        GLib.timeout_add(100, self._cps_tick)
        g.add(area)
        return g

    def _stat(self, parent: Gtk.Box, caption: str) -> Gtk.Label:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        val = Gtk.Label(label="0")
        val.add_css_class("cps-value")
        cap = Gtk.Label(label=caption)
        cap.add_css_class("cps-caption")
        box.append(val)
        box.append(cap)
        parent.append(box)
        return val

    def _cps_reset(self) -> None:
        self.cps_times.clear()
        self.cps_best = 0
        self.cps_min_gap = None
        self._cps_render()

    def _on_raw_click(self, t: float, code: int) -> None:
        if code != BTN_LEFT or not self.cps_inside:
            return
        if self.cps_times:
            gap = t - self.cps_times[-1]
            if gap > 2.0:  # uzun ara: yeni seri
                self.cps_times.clear()
            elif self.cps_min_gap is None or gap < self.cps_min_gap:
                self.cps_min_gap = gap
        self.cps_times.append(t)
        self._cps_render()

    def _cps_current(self) -> int:
        if not self.cps_times:
            return 0
        now = time.time()
        if now - self.cps_times[-1] > 1.0:
            return 0
        return sum(1 for t in self.cps_times if t > now - 1.0)

    def _cps_render(self) -> None:
        cur = self._cps_current()
        self.cps_best = max(self.cps_best, cur)
        self.cps_now.set_label(str(cur))
        self.cps_peak.set_label(str(self.cps_best))
        self.cps_min.set_label(f"{self.cps_min_gap * 1000:.1f} ms" if self.cps_min_gap else "—")
        self.cps_total.set_label(str(len(self.cps_times)))
        if self.cfg.debounce_enabled and self.cfg.debounce_ms > 0:
            self.cps_hint.set_label(
                f"Debounce açık ({self.cfg.debounce_ms} ms): drag click sınırlanır, kapatman önerilir"
            )
        elif self.mouse is None or self.meter.fd < 0:
            self.cps_hint.set_label("Fare olay cihazı okunamıyor")
        else:
            self.cps_hint.set_label("Buraya tıklayarak test et")

    def _cps_tick(self):
        self._cps_render()
        return GLib.SOURCE_CONTINUE

    def _build_click(self) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(
            title="Tıklama",
            description="Yazılımsal debounce: switch titremesinden kaynaklanan istemsiz çift "
            "tıklamaları süzer. Basma gecikmesizdir; yalnızca bırakma bu süre kadar beklenir. "
            "Arka plan servisi gerektirir.",
        )
        self.debounce_row = Adw.ExpanderRow(
            title="Debounce filtresi", show_enable_switch=True,
            enable_expansion=self.cfg.debounce_enabled, expanded=self.cfg.debounce_enabled,
        )
        self.debounce_row.connect("notify::enable-expansion", self._on_debounce_toggle)

        self.debounce_spin = Adw.SpinRow(
            title="Tıklama tepki süresi",
            subtitle="Bırakmadan sonra yeni basmanın arıza sayılacağı süre (ms)",
            adjustment=Gtk.Adjustment(lower=1, upper=50, step_increment=1, page_increment=5,
                                      value=self.cfg.debounce_ms),
            numeric=True,
        )
        self.debounce_spin.get_adjustment().connect("value-changed", self._on_debounce_ms)
        self.debounce_row.add_row(self.debounce_spin)

        self.minclick_spin = Adw.SpinRow(
            title="En kısa tıklama aralığı",
            subtitle="İki basma arası en az bu kadar ms olmalı (0 = sınırsız)",
            adjustment=Gtk.Adjustment(lower=0, upper=500, step_increment=5, page_increment=25,
                                      value=self.cfg.min_click_ms),
            numeric=True,
        )
        self.minclick_spin.get_adjustment().connect("value-changed", self._on_minclick)
        self.debounce_row.add_row(self.minclick_spin)

        presets = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=6, margin_bottom=6, margin_end=12)
        for label, ms in (("4 ms", 4), ("8 ms", 8), ("16 ms", 16), ("24 ms", 24)):
            b = Gtk.Button(label=label)
            b.add_css_class("pill")
            b.add_css_class("small")
            b.connect("clicked", lambda _b, v=ms: self.debounce_spin.set_value(v))
            presets.append(b)
        preset_row = Adw.ActionRow(title="Hazır değerler")
        preset_row.add_suffix(presets)
        self.debounce_row.add_row(preset_row)
        g.add(self.debounce_row)
        return g

    def _build_misc(self) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(title="Diğer")
        light = Adw.ActionRow(title="Işık seviyesi")
        self.light_tg = self._toggle_group(
            [("0", "Kapalı"), ("1", "1"), ("2", "2"), ("3", "3")],
            str(self.cfg.backlight), self._on_light,
        )
        light.add_suffix(self.light_tg)
        g.add(light)
        self.wheel_row = Adw.SwitchRow(title="Kaydırma tekerleği", active=self.cfg.wheel_enabled)
        self.wheel_row.connect("notify::active", self._on_wheel)
        g.add(self.wheel_row)
        return g

    def _build_service(self) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(
            title="Arka plan servisi",
            description="Fare takıldığında ayarları otomatik uygular, DPI tuşunu dinler ve "
            "debounce filtresini çalıştırır. (DPI/Hz fare belleğinde kalıcı değildir.)",
        )
        self.service_row = Adw.SwitchRow(title="Oturum açılınca başlat")
        self.service_row.connect("notify::active", self._on_service)
        g.add(self.service_row)
        self._refresh_service()
        return g

    # --- cihaz -----------------------------------------------------------

    def refresh_device(self) -> None:
        devs = find_devices()
        if self.mouse and (not devs or devs[0].path != self.mouse.info.path):
            self.mouse.close()
            self.mouse = None
        if self.mouse is None and devs:
            try:
                self.mouse = BloodyMouse(devs[0])
                self.info = mouse_sensor(self.mouse)
                self._loading = True
                try:
                    self.light_tg.set_active_name(str(self.mouse.get_backlight()))
                finally:
                    self._loading = False
                self._rebuild_slots()
            except MouseError as e:
                self.mouse = None
                self.toast(str(e))
        if self.mouse:
            self.model_label.set_label(self.mouse.info.name.upper())
            sens = f"{self.info.label} · en fazla {self.info.max_cpi} DPI" if self.info else "Sensör bilinmiyor"
            self.sub_label.set_label(sens)
            self._set_chip(True)
        else:
            self.sub_label.set_label("Fare bulunamadı")
            self._set_chip(False)

    def _set_chip(self, ok: bool) -> None:
        self.status_chip.set_label("BAĞLI" if ok else "BAĞLI DEĞİL")
        self.status_chip.remove_css_class("bad" if ok else "ok")
        self.status_chip.add_css_class("ok" if ok else "bad")

    def _poll_device(self):
        was = self.mouse is not None
        self.refresh_device()
        if not was and self.mouse:
            self.apply_now()
        self._refresh_service()
        return GLib.SOURCE_CONTINUE

    def apply_now(self, toast: bool = False) -> None:
        self._apply_source = 0
        if not self.mouse:
            if toast:
                self.toast("Fare bağlı değil")
            return
        try:
            warnings = apply_config(self.mouse, self.cfg, self.info)
            for w in warnings:
                self.toast(w)
            if toast and not warnings:
                self.toast("Ayarlar uygulandı")
        except (MouseError, ValueError) as e:
            self.toast(str(e))
            self.mouse.close()
            self.mouse = None
            self.refresh_device()

    def changed(self, hardware: bool = True) -> None:
        """Ayarı kaydet, kısa bir gecikmeyle fareye uygula."""
        if self._loading:
            return
        self.cfg.save()
        if hardware:
            if self._apply_source:
                GLib.source_remove(self._apply_source)
            self._apply_source = GLib.timeout_add(150, lambda: self.apply_now() or False)
        if self.cfg.debounce_enabled and not self._service_active():
            self.toast("Debounce için arka plan servisini aç")

    # --- olaylar ---------------------------------------------------------

    def _on_rate(self, name):
        self.cfg.rate_hz = int(name)
        self.rate_row.set_subtitle(f"{self.cfg.rate_hz} Hz")
        self.meter.gaps.clear()
        self.changed()

    def _on_light(self, name):
        self.cfg.backlight = int(name)
        self.changed()

    def _on_wheel(self, row, _p):
        self.cfg.wheel_enabled = row.get_active()
        self.changed()

    def _on_dpi_changed(self, adj, i):
        v = int(round(adj.get_value() / 50) * 50)
        self.cfg.dpi_slots[i] = v
        self.changed(hardware=i == self.cfg.active_slot)

    def _on_slot_select(self, check, i):
        if not check.get_active() or self._loading:
            return
        self.cfg.active_slot = i
        self.changed()
        GLib.idle_add(lambda: self._rebuild_slots() or False)

    def _on_add_slot(self, _b):
        if len(self.cfg.dpi_slots) >= MAX_SLOTS:
            return
        nxt = min(self.cfg.dpi_slots[-1] * 2, self.info.max_cpi if self.info else 4000)
        self.cfg.dpi_slots.append(nxt)
        self._rebuild_slots()
        self.changed()

    def _on_remove_slot(self, _b, i):
        del self.cfg.dpi_slots[i]
        if self.cfg.active_slot >= len(self.cfg.dpi_slots):
            self.cfg.active_slot = len(self.cfg.dpi_slots) - 1
        elif self.cfg.active_slot > i:
            self.cfg.active_slot -= 1
        self._rebuild_slots()
        self.changed()

    def _on_debounce_toggle(self, row, _p):
        self.cfg.debounce_enabled = row.get_enable_expansion()
        self.changed(hardware=False)

    def _on_debounce_ms(self, adj):
        self.cfg.debounce_ms = int(adj.get_value())
        self.changed(hardware=False)

    def _on_minclick(self, adj):
        self.cfg.min_click_ms = int(adj.get_value())
        self.changed(hardware=False)

    def _on_hz(self, hz):
        if hz is None:
            self.hz_label.set_label("—")
            self.hz_hint.set_label(f"Ayarlı: {1000 // self.cfg.rate_hz} ms ({self.cfg.rate_hz} Hz)\nÖlçmek için fareyi oynat")
        else:
            self.hz_label.set_label(f"{hz:.0f}")
            self.hz_hint.set_label(f"Ayarlı: {1000 // self.cfg.rate_hz} ms ({self.cfg.rate_hz} Hz)\ncanlı ölçüm")
        self.spark.queue_draw()

    def _draw_spark(self, area, cr, w, h):
        hist = list(self.meter.history)
        top = 1100.0
        # kılavuz çizgileri
        cr.set_line_width(1)
        for lvl in (125, 250, 500, 1000):
            y = h - (lvl / top) * (h - 4) - 2
            cr.set_source_rgba(1, 1, 1, 0.07)
            cr.move_to(0, y)
            cr.line_to(w, y)
            cr.stroke()
        if len(hist) < 2:
            return
        step = w / (self.meter.history.maxlen - 1)
        x0 = w - step * (len(hist) - 1)
        cr.set_source_rgba(0.78, 0.06, 0.18, 1)
        cr.set_line_width(2)
        for i, v in enumerate(hist):
            x = x0 + i * step
            y = h - (min(v, top) / top) * (h - 4) - 2
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke_preserve()
        cr.line_to(w, h)
        cr.line_to(x0, h)
        cr.close_path()
        cr.set_source_rgba(0.78, 0.06, 0.18, 0.18)
        cr.fill()

    # --- servis ----------------------------------------------------------

    def _systemctl(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(["systemctl", "--user", *args, SERVICE], capture_output=True, text=True)

    def _service_active(self) -> bool:
        return self._systemctl("is-active").stdout.strip() == "active"

    def _refresh_service(self) -> None:
        enabled = self._systemctl("is-enabled").stdout.strip() == "enabled"
        active = self._service_active()
        installed = self._systemctl("cat").returncode == 0
        self._loading = True
        self.service_row.set_active(enabled)
        self._loading = False
        self.service_row.set_sensitive(installed)
        if not installed:
            self.service_row.set_subtitle("Kurulu değil — install.sh çalıştır")
        else:
            self.service_row.set_subtitle("Çalışıyor" if active else "Durdu")

    def _on_service(self, row, _p):
        if self._loading:
            return
        r = self._systemctl("enable" if row.get_active() else "disable", "--now")
        if r.returncode != 0:
            self.toast(r.stderr.strip() or "systemctl hatası")
        self._refresh_service()

    # --- yardımcılar -----------------------------------------------------

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=3))

    def _on_close(self, *_):
        self.meter.close()
        if self.mouse:
            self.mouse.close()
        return False


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._activate)

    def _activate(self, app):
        win = self.props.active_window
        if not win:
            provider = Gtk.CssProvider()
            provider.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
            win = Window(app)
        win.present()


def main() -> int:
    return App().run([sys.argv[0]])
