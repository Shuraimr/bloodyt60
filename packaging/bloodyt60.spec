Name:           bloodyt60
Version:        1.0.1
Release:        1%{?dist}
Summary:        A4Tech Bloody T60 fare sürücüsü ve ayar arayüzü
License:        GPL-3.0-or-later
URL:            https://github.com/Shuraimr/bloodyt60
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  systemd-rpm-macros
Requires:       python3
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       systemd-udev
Requires:       libinput

%description
A4Tech Bloody T60 (ve benzeri Bloody) fareler için Linux yapılandırıcı:
1/2/4/8 ms polling aralığı, DPI kademeleri, ışık seviyesi, tekerlek,
yazılımsal tıklama debounce'u, canlı Hz ölçer ve CPS testi. GTK4/libadwaita
arayüzü ve ayarları otomatik uygulayan kullanıcı servisi içerir.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{_datadir}/bloodyt60
cp -r bloodyt60 %{buildroot}%{_datadir}/bloodyt60/
install -Dm755 bin/bloodyt60 %{buildroot}%{_bindir}/bloodyt60
install -Dm644 data/70-bloodyt60.rules %{buildroot}%{_udevrulesdir}/70-bloodyt60.rules
install -Dm644 data/50-bloodyt60.quirks %{buildroot}%{_datadir}/libinput/50-bloodyt60.quirks
install -Dm644 data/bloodyt60.service %{buildroot}%{_userunitdir}/bloodyt60.service
install -Dm644 data/io.github.bloodyt60.desktop %{buildroot}%{_datadir}/applications/io.github.bloodyt60.desktop

%post
%udev_rules_update
udevadm trigger --subsystem-match=hidraw --subsystem-match=input --subsystem-match=misc >/dev/null 2>&1 || :
%systemd_user_post bloodyt60.service

%preun
%systemd_user_preun bloodyt60.service

%postun
%udev_rules_update

%files
%license LICENSE
%doc README.md
%{_bindir}/bloodyt60
%{_datadir}/bloodyt60/
%{_udevrulesdir}/70-bloodyt60.rules
%{_datadir}/libinput/50-bloodyt60.quirks
%{_userunitdir}/bloodyt60.service
%{_datadir}/applications/io.github.bloodyt60.desktop

%changelog
* Fri Nov 20 2026 Shuraimr <231307236+Shuraimr@users.noreply.github.com> - 1.0.1-1
- libinput debounce'u A4Tech fareleri için kapatıldı (drag click düzeltmesi)

* Fri Nov 20 2026 Shuraimr <231307236+Shuraimr@users.noreply.github.com> - 1.0.0-1
- İlk sürüm
