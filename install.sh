#!/bin/sh
# Kullanıcı kurulumu (root gerekmez). udev kuralı için ayrıca: sudo ./install-udev.sh
set -e
cd "$(dirname "$0")"
SHARE="$HOME/.local/share/bloodyt60"
mkdir -p "$SHARE" "$HOME/.local/bin" "$HOME/.config/systemd/user" "$HOME/.local/share/applications"
rm -rf "$SHARE/bloodyt60"
cp -r bloodyt60 "$SHARE/"
find "$SHARE" -name __pycache__ -prune -exec rm -rf {} +
cat > "$HOME/.local/bin/bloodyt60" <<EOS
#!/bin/sh
PYTHONPATH="$SHARE" exec python3 -m bloodyt60 "\$@"
EOS
chmod +x "$HOME/.local/bin/bloodyt60"
sed "s|^ExecStart=.*|ExecStart=$HOME/.local/bin/bloodyt60 daemon|" data/bloodyt60.service > "$HOME/.config/systemd/user/bloodyt60.service"
install -m644 data/io.github.bloodyt60.desktop "$HOME/.local/share/applications/io.github.bloodyt60.desktop"
install -Dm644 data/io.github.bloodyt60.svg "$HOME/.local/share/icons/hicolor/scalable/apps/io.github.bloodyt60.svg"
systemctl --user daemon-reload
systemctl --user enable --now bloodyt60.service
systemctl --user restart bloodyt60.service
[ -e /etc/udev/rules.d/70-bloodyt60.rules ] || echo "UYARI: udev kuralı yok, şunu çalıştır: sudo ./install-udev.sh"
echo "Kuruldu. Arayüz: bloodyt60 gui (veya uygulama menüsünden 'Bloody T60')"
