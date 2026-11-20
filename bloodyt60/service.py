"""Arka plan servisini yönetme: systemd (normal kurulum) veya Flatpak portalı.

Flatpak içinde systemctl yoktur; servis Background portalı ile oturum
açılışına eklenir ve doğrudan alt süreç olarak başlatılır. Hangi yolla
çalışırsa çalışsın servis tek kopya kalsın diye bir kilit dosyası tutar.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess

SERVICE = "bloodyt60.service"
APP_ID = "io.github.bloodyt60"
IN_FLATPAK = os.path.exists("/.flatpak-info")


def _runtime_dir() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if IN_FLATPAK:
        base = os.path.join(base, "app", APP_ID)
    os.makedirs(base, exist_ok=True)
    return base


LOCK_PATH = os.path.join(_runtime_dir(), "bloodyt60-daemon.lock")


def acquire_daemon_lock():
    """Servis süreci çağırır. Başka kopya çalışıyorsa None döner."""
    f = open(LOCK_PATH, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.write(str(os.getpid()))
    f.flush()
    return f


def daemon_running() -> bool:
    try:
        with open(LOCK_PATH) as f:
            try:
                fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
    except FileNotFoundError:
        return False


def _systemctl(*args) -> subprocess.CompletedProcess | None:
    if not shutil.which("systemctl"):
        return None
    return subprocess.run(["systemctl", "--user", *args, SERVICE], capture_output=True, text=True)


class ServiceStatus:
    def __init__(self, installed: bool, enabled: bool, active: bool, note: str = ""):
        self.installed = installed
        self.enabled = enabled
        self.active = active
        self.note = note


def status() -> ServiceStatus:
    active = daemon_running()
    if IN_FLATPAK:
        return ServiceStatus(True, _flatpak_autostart_enabled(), active)
    r = _systemctl("cat")
    if r is None or r.returncode != 0:
        return ServiceStatus(False, False, active, "Kurulu değil — install.sh çalıştır")
    enabled = (_systemctl("is-enabled").stdout.strip() == "enabled")
    return ServiceStatus(True, enabled, active)


def set_enabled(enable: bool) -> str | None:
    """Hata mesajı veya None döner."""
    if IN_FLATPAK:
        err = _flatpak_request_background(enable)
        if err:
            return err
        if enable and not daemon_running():
            start_detached()
        elif not enable:
            stop_running()
        return None
    r = _systemctl("enable" if enable else "disable", "--now")
    if r is None:
        return "systemctl bulunamadı"
    return None if r.returncode == 0 else (r.stderr.strip() or "systemctl hatası")


def start_detached() -> None:
    subprocess.Popen(
        ["bloodyt60", "daemon"], start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def stop_running() -> None:
    try:
        with open(LOCK_PATH) as f:
            pid = int(f.read().strip() or 0)
        if pid > 0:
            os.kill(pid, 15)
    except (OSError, ValueError):
        pass


# --- Flatpak Background portalı -------------------------------------------

_AUTOSTART_FLAG = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "bloodyt60", "autostart"
)


def _flatpak_autostart_enabled() -> bool:
    return os.path.exists(_AUTOSTART_FLAG)


def _flatpak_request_background(enable: bool) -> str | None:
    try:
        from gi.repository import Gio, GLib
    except ImportError:
        return "GLib bulunamadı"
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        options = {
            "reason": GLib.Variant("s", "Fare ayarlarını uygulamak ve tıklama filtresini çalıştırmak"),
            "autostart": GLib.Variant("b", enable),
            "commandline": GLib.Variant("as", ["bloodyt60", "daemon"]),
            "dbus-activatable": GLib.Variant("b", False),
        }
        bus.call_sync(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Background", "RequestBackground",
            GLib.Variant("(sa{sv})", ("", options)), None, Gio.DBusCallFlags.NONE, 10000, None,
        )
    except GLib.Error as e:
        return f"Arka plan izni alınamadı: {e.message}"
    os.makedirs(os.path.dirname(_AUTOSTART_FLAG), exist_ok=True)
    if enable:
        open(_AUTOSTART_FLAG, "w").close()
    elif os.path.exists(_AUTOSTART_FLAG):
        os.remove(_AUTOSTART_FLAG)
    return None


# --- sistem kurulumu (udev + libinput) kontrolü -----------------------------

def host_setup_command() -> str:
    """Sisteme udev kuralı ve libinput istisnasını kuran komut."""
    if IN_FLATPAK:
        return (f'sudo sh "$(flatpak info --show-location {APP_ID})/files/share/bloodyt60/host/host-setup.sh"')
    return "sudo ./install-udev.sh"
