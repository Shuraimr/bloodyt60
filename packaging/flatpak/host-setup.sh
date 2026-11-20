#!/bin/sh
# Flatpak kurulumu için sistem tarafı: udev izinleri ve libinput istisnası.
# Flatpak bu dosyaları kendisi kuramaz; bir kez root olarak çalıştır.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
install -Dm644 "$DIR/70-bloodyt60.rules" /etc/udev/rules.d/70-bloodyt60.rules
# /usr salt okunur olabilir (Silverblue vb.); libinput /etc altındaki dosyayı da okur.
mkdir -p /etc/libinput
Q=/etc/libinput/local-overrides.quirks
if ! grep -q "Bloody A4Tech mice" "$Q" 2>/dev/null; then
  { [ -s "$Q" ] && echo; cat "$DIR/50-bloodyt60.quirks"; } >> "$Q"
fi
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --subsystem-match=input --subsystem-match=misc
echo "Kuruldu. libinput değişikliği için oturumu kapatıp yeniden aç (veya yeniden başlat)."
