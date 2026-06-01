#!/bin/bash
# build_wasm.sh — Build the Widget Shell as a WASM binary.
#
# Prerequisites:
#   - Emscripten SDK (emsdk) activated in PATH
#   - Qt 6.x built for WASM (qt-wasm prefix) with Widgets + UiTools
#
# Usage:
#   ./build_wasm.sh [qt-wasm-prefix]
#
# Example:
#   ./build_wasm.sh ~/Qt/6.6.0/wasm_singlethread

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build_wasm"
QT_WASM_PREFIX="${1:-}"

if [ -z "$QT_WASM_PREFIX" ]; then
    echo "Usage: $0 <qt-wasm-prefix>"
    echo ""
    echo "Example: $0 ~/Qt/6.6.0/wasm_singlethread"
    exit 1
fi

if [ ! -f "$QT_WASM_PREFIX/lib/cmake/Qt6/Qt6Config.cmake" ]; then
    echo "ERROR: Qt6Config.cmake not found in $QT_WASM_PREFIX"
    echo "Make sure the path points to a Qt WASM build."
    exit 1
fi

echo "=== Building Widget Shell (WASM) ==="
echo "Qt prefix: $QT_WASM_PREFIX"
echo "Build dir: $BUILD_DIR"
echo ""

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Configure with CMake and Emscripten toolchain.
"$QT_WASM_PREFIX/bin/qt-cmake" \
    -DCMAKE_BUILD_TYPE=Release \
    "$SCRIPT_DIR"

# Build.
cmake --build . --parallel

echo ""
echo "=== Build complete ==="
echo "Output files:"
ls -lh widgetshell.js widgetshell.wasm 2>/dev/null || echo "(check build directory for output)"

# --- Deploy to web/widget-shell/ ---
DEPLOY_DIR="${SCRIPT_DIR}/../web/widget-shell"
echo ""
echo "=== Deploying to web/widget-shell/ ==="
mkdir -p "$DEPLOY_DIR"
cp widgetshell.js   "$DEPLOY_DIR/"
cp widgetshell.wasm "$DEPLOY_DIR/"
echo "  Copied widgetshell.js"
echo "  Copied widgetshell.wasm"
echo ""
echo "=== Deploy complete ==="
