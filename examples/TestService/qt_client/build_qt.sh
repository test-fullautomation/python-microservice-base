#!/usr/bin/env bash
# Build the Qt-native client.  Set QT_DIR to your Qt install prefix
# (one that contains bin/qmake6, lib/cmake/Qt6, …).

set -euo pipefail
: "${QT_DIR:?Set QT_DIR to the Qt install prefix (e.g. /opt/Qt/6.11.0/gcc_64)}"
export Qt6_DIR="${Qt6_DIR:-$QT_DIR/lib/cmake/Qt6}"

BUILD="$(dirname "$(readlink -f "$0")")/build-qt"
mkdir -p "$BUILD"
cd "$BUILD"

cmake -G Ninja -DCMAKE_BUILD_TYPE=Release ..
cmake --build .

echo "Qt client built: $BUILD/test_service_qt_gui"
