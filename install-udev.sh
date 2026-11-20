#!/bin/sh
# udev kuralını ve libinput istisnasını kurar (root gerekir).
set -e
cd "$(dirname "$0")"
install -Dm644 data/70-bloodyt60.rules /etc/udev/rules.d/70-bloodyt60.rules
install -Dm644 data/50-bloodyt60.quirks /usr/share/libinput/50-bloodyt60.quirks
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --subsystem-match=input --subsystem-match=misc
echo "Kuruldu. libinput değişikliği için oturumu kapatıp yeniden aç."
