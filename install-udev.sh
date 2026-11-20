#!/bin/sh
# udev kuralını kurar (root gerekir) ve fareyi yeniden tetikler.
set -e
cd "$(dirname "$0")"
install -Dm644 data/70-bloodyt60.rules /etc/udev/rules.d/70-bloodyt60.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --subsystem-match=input --subsystem-match=misc
echo "udev kuralı kuruldu."
