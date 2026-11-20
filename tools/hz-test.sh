#!/bin/sh
# Hz komutunu doğrular: mevcut, 1000 Hz, 500 Hz ve tekrar 1000 Hz ölçer.
cd "$(dirname "$0")/.."
echo "== Şu anki hız"; python3 -m bloodyt60 measure --seconds 4
for hz in 1000 500 1000; do
  python3 -m bloodyt60 set --hz $hz >/dev/null && echo "== $hz Hz ayarlandı (2 sn sonra ölçüm)"
  sleep 2
  python3 -m bloodyt60 measure --seconds 4
done
