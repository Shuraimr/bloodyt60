#!/bin/sh
systemctl --user disable --now bloodyt60.service 2>/dev/null
rm -rf "$HOME/.local/share/bloodyt60" "$HOME/.local/bin/bloodyt60" \
  "$HOME/.config/systemd/user/bloodyt60.service" \
  "$HOME/.local/share/applications/io.github.bloodyt60.desktop" \
  "$HOME/.local/share/icons/hicolor/scalable/apps/io.github.bloodyt60.svg"
systemctl --user daemon-reload
echo "Kaldırıldı. (root dosyaları: sudo rm /etc/udev/rules.d/70-bloodyt60.rules /usr/share/libinput/50-bloodyt60.quirks)"
