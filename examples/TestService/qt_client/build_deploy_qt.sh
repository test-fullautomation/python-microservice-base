#!/usr/bin/env bash
# Build + deploy the Qt-native client into dist-qt/.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${QT_DIR:?Set QT_DIR to your Qt install prefix}"

BUILD="$SCRIPT_DIR/build-qt"
DIST="$SCRIPT_DIR/dist-qt"
EXE_NAME="test_service_qt_gui"

"$SCRIPT_DIR/build_qt.sh"
[[ -f "$BUILD/$EXE_NAME" ]] || { echo "Binary not found at $BUILD/$EXE_NAME"; exit 1; }

mkdir -p "$DIST"
cp -f "$BUILD/$EXE_NAME" "$DIST/"

if [[ "$OSTYPE" == "linux-gnu"* ]] && command -v linuxdeployqt >/dev/null; then
    linuxdeployqt "$DIST/$EXE_NAME" -bundle-non-qt-libs
elif [[ "$OSTYPE" == "darwin"* ]]; then
    "$QT_DIR/bin/macdeployqt" "$DIST/$EXE_NAME.app" || true
fi

echo "Qt client deployed: $DIST/$EXE_NAME"
echo "On Linux you may need: export LD_LIBRARY_PATH=\"$QT_DIR/lib\""
