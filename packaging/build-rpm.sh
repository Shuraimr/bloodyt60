#!/bin/sh
# RPM paketini dist/ altına derler.
set -e
cd "$(dirname "$0")/.."
VER=$(sed -n 's/^Version: *//p' packaging/bloodyt60.spec)
TOP="$PWD/rpmbuild"
rm -rf "$TOP"; mkdir -p "$TOP/SOURCES" dist
tar --transform "s,^,bloodyt60-$VER/," --exclude=__pycache__ \
  -czf "$TOP/SOURCES/bloodyt60-$VER.tar.gz" bloodyt60 bin data LICENSE README.md
rpmbuild --define "_topdir $TOP" -ba packaging/bloodyt60.spec
cp "$TOP"/RPMS/noarch/*.rpm "$TOP"/SRPMS/*.rpm dist/
ls -1 dist/
