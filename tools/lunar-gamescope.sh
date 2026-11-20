#!/bin/sh
# Lunar Client'ı gamescope içinde başlatır (xwayland-satellite devre dışı kalır).
# Önce açık Lunar kopyalarını kapatır; aksi halde yeni kopya hemen çıkar.
APPIMAGE="${LUNAR_APPIMAGE:-$HOME/AppImages/lunar_client.appimage}"

if pgrep -f 'lunar_client.appimage|\.mount_lunar|\.lunarclient/jre' >/dev/null; then
  echo "Açık Lunar Client kapatılıyor..."
  pkill -f 'lunar_client.appimage'
  pkill -f '\.mount_lunar'
  pkill -f '\.lunarclient/jre'
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    pgrep -f 'lunar_client.appimage|\.mount_lunar|\.lunarclient/jre' >/dev/null || break
    sleep 0.5
  done
  pkill -9 -f 'lunar_client.appimage|\.mount_lunar|\.lunarclient/jre' 2>/dev/null
fi

exec gamescope -f -W 1920 -H 1080 --force-grab-cursor -- "$APPIMAGE"
