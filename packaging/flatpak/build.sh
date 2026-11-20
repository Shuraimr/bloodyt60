#!/bin/sh
# Flatpak paketini derler: dist/bloodyt60.flatpak
# Gerekenler: flatpak install --user flathub org.flatpak.Builder org.gnome.Sdk//51
set -e
cd "$(dirname "$0")/../.."
mkdir -p dist
flatpak run org.flatpak.Builder --user --force-clean --repo=repo build-flatpak packaging/flatpak/io.github.bloodyt60.yml
flatpak build-bundle repo dist/bloodyt60.flatpak io.github.bloodyt60
echo "Hazır: dist/bloodyt60.flatpak"
