# bloodyt60

A4Tech **Bloody T60** (09da:7c5e) için Linux yapılandırıcı: GTK4/libadwaita arayüzü,
arka plan servisi ve komut satırı. Ek Python paketi gerekmez (python3-gobject, gtk4,
libadwaita Fedora'da hazır gelir). Diğer Bloody fareleriyle de büyük ölçüde uyumludur.

## Özellikler

| Özellik | Nasıl |
|---|---|
| Polling aralığı 1 / 2 / 4 / 8 ms (1000–125 Hz) | Donanım (`0x0D` komutu) |
| DPI, 5 kademeye kadar, DPI tuşuyla geçiş | Donanım + servis |
| Işık seviyesi (kapalı / 1 / 2 / 3) | Donanım (`0x11`) |
| Kaydırma tekerleği aç/kapa | Donanım (`0x16`) |
| Tıklama tepki süresi (debounce), en kısa tıklama aralığı | Yazılım (evdev + uinput) |
| Canlı Hz ölçer, CPS testi (drag click) | Arayüz |

DPI ve Hz farenin belleğinde **kalıcı değildir**; fare çıkarılıp takıldığında servis
ayarları yeniden uygular.

**Drag click:** libinput, titreşen tuşları kendi başına süzer ve bu drag click'i
öldürür. Paket, A4Tech fareleri için libinput debounce'unu kapatan bir istisna kurar
(`50-bloodyt60.quirks`). Kurduktan sonra **oturumu kapatıp yeniden aç**.

**1 ms neden en düşük değer?** T60 bir USB 1.1 Full-Speed cihazıdır; bu sınıfta
kesme uç noktası en sık 1 ms'de (bir USB frame'i) bir yoklanabilir. 1 ms = 1000 Hz
farenin ve bağlantının fiziksel sınırıdır.

## Kurulum

### RPM (Fedora)

[Releases](https://github.com/Shuraimr/bloodyt60/releases) sayfasından RPM'i indir:

```bash
sudo dnf install ./bloodyt60-*.noarch.rpm
systemctl --user enable --now bloodyt60
```

Kurulumdan sonra fareyi bir kez çıkarıp tak (udev izinleri için). Arayüz uygulama
menüsünde "Bloody T60" adıyla bulunur.

Kaynaktan RPM derlemek için: `./packaging/build-rpm.sh` (çıktı `dist/` altında).

### Paketsiz (~/.local)

```bash
sudo ./install-udev.sh   # bir kez: fareye root olmadan erişim
./install.sh             # ~/.local altına kurar, kullanıcı servisini başlatır
bloodyt60 gui
```

Kaldırmak için `./uninstall.sh`. RPM ile paketsiz kurulumu aynı anda kullanma.

## Komut satırı

```bash
bloodyt60 info                     # model, sensör, ışık
bloodyt60 set --ms 1 --dpi 1600   # 1 ms polling (1000 Hz), 1600 DPI
bloodyt60 set --debounce 8         # debounce 8 ms (0 = kapalı)
bloodyt60 measure                  # gerçek rapor hızını ölç (fareyi oynat)
```

Ayarlar: `~/.config/bloodyt60/config.json`. Servis günlüğü:
`journalctl --user -u bloodyt60 -f`.

## Debounce nasıl çalışır

Servis farenin olay cihazını özel olarak yakalar ve aynı yeteneklere sahip sanal bir
fare oluşturur. Basmalar anında iletilir; bırakma, ayarlanan süre kadar bekletilir ve
bu süre içinde gelen yeni basma (switch titremesi) bırakmayla birlikte yutulur. Böylece
tıklamaya gecikme eklenmeden istemsiz çift tıklamalar giderilir.

## Protokol

Arayüz 2 (üretici sayfası 0xFF31), rapor kimliği 7, 72 baytlık feature raporları.
Opcode'lar [maxmati/a4tech-bloody-linux-driver](https://github.com/maxmati/a4tech-bloody-linux-driver)
ve [C0rn3j/a4tech_bloody_p85_driver](https://gitlab.com/C0rn3j/a4tech_bloody_p85_driver)
çalışmalarından alınmıştır. Not: o araçlar `0x0D` komutunda rapor hızı baytını sabit `02`
gönderir, bu da fareyi 500 Hz'e düşürür.
