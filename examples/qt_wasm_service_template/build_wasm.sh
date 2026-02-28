#!/usr/bin/env bash
# ===================================================================
# build_wasm.sh — Build the Qt WASM GUI and copy output to GUIs/
# ===================================================================
#
# Usage:
#   ./build_wasm.sh              Build Release (default)
#   ./build_wasm.sh debug        Build Debug
#   ./build_wasm.sh clean        Delete WASM build folder
#
# Prerequisites:
#   - Qt 6.5+ with wasm_singlethread target
#   - Emscripten matching your Qt version (e.g., 3.1.50 for Qt 6.7.1)
#   - CMake 3.21+ and Ninja build system
#
# Output:
#   GUIs/
#   ├── myqtwasmservice.wasm     WASM binary
#   └── myqtwasmservice.js       Emscripten JS loader
# ===================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ----- Configurable paths (edit these or set via environment) -----
QT_WASM_DIR="${QT_WASM_DIR:-/opt/qt/6.7.1/wasm_singlethread}"
QT_HOST_DIR="${QT_HOST_DIR:-/opt/qt/6.7.1/gcc_64}"
EMSDK_DIR="${EMSDK_DIR:-/opt/emsdk}"

# ----- Derived paths -----
BUILD_DIR="$SCRIPT_DIR/build/wasm"
EMSCRIPTEN_DIR="$EMSDK_DIR/upstream/emscripten"

# ----- Parse arguments -----
BUILD_TYPE="Release"

case "${1:-}" in
    debug|Debug)
        BUILD_TYPE="Debug"
        ;;
    clean)
        echo "Cleaning WASM build folder..."
        rm -rf "$BUILD_DIR"
        echo "Done."
        exit 0
        ;;
esac

# ----- Validate prerequisites -----
if [ ! -f "$QT_WASM_DIR/lib/cmake/Qt6/qt.toolchain.cmake" ]; then
    echo "ERROR: Qt WASM kit not found at $QT_WASM_DIR"
    echo "       Edit QT_WASM_DIR in this script or set via environment."
    echo "       Install via Qt Maintenance Tool: Qt > 6.x > WebAssembly"
    exit 1
fi
if [ ! -d "$QT_HOST_DIR" ]; then
    echo "ERROR: Qt host kit not found at $QT_HOST_DIR"
    echo "       Edit QT_HOST_DIR in this script (needed for moc/rcc/uic)."
    exit 1
fi
if [ ! -f "$EMSCRIPTEN_DIR/emcc" ] && [ ! -f "$EMSCRIPTEN_DIR/emcc.py" ]; then
    echo "ERROR: Emscripten not found at $EMSCRIPTEN_DIR"
    echo "       Edit EMSDK_DIR in this script."
    exit 1
fi
if ! command -v ninja &>/dev/null && ! command -v cmake &>/dev/null; then
    echo "ERROR: cmake or ninja not found in PATH."
    exit 1
fi

# ----- Setup Emscripten environment -----
echo ""
echo "===== Setting up Emscripten ====="

# Source emsdk environment (sets PATH, EMSDK, etc.)
if [ -f "$EMSDK_DIR/emsdk_env.sh" ]; then
    source "$EMSDK_DIR/emsdk_env.sh"
else
    echo "  WARNING: emsdk_env.sh not found. Setting PATH manually."
    export PATH="$EMSCRIPTEN_DIR:$EMSDK_DIR:$PATH"
    export EMSDK="$EMSDK_DIR"
fi

echo "  EMSDK=${EMSDK:-not set}"

# Verify emcc
if command -v emcc &>/dev/null; then
    echo "  $(emcc --version 2>/dev/null | head -1)"
else
    echo "  WARNING: emcc not in PATH — build may fail."
fi

# ----- Configure -----
echo ""
echo "===== Configuring Qt WASM Build [$BUILD_TYPE] ====="
echo "  Qt WASM: $QT_WASM_DIR"
echo "  Qt Host: $QT_HOST_DIR"
echo ""

QT_TOOLCHAIN="$QT_WASM_DIR/lib/cmake/Qt6/qt.toolchain.cmake"
EM_TOOLCHAIN="$EMSCRIPTEN_DIR/cmake/Modules/Platform/Emscripten.cmake"

# Determine generator: prefer Ninja, fallback to Unix Makefiles
CMAKE_GEN_ARGS=()
if command -v ninja &>/dev/null; then
    CMAKE_GEN_ARGS+=(-G Ninja)
else
    CMAKE_GEN_ARGS+=(-G "Unix Makefiles")
fi

cmake "${CMAKE_GEN_ARGS[@]}" \
    -DCMAKE_TOOLCHAIN_FILE="$QT_TOOLCHAIN" \
    -DQT_CHAINLOAD_TOOLCHAIN_FILE="$EM_TOOLCHAIN" \
    -B "$BUILD_DIR" \
    -S "$SCRIPT_DIR" \
    -DQT_HOST_PATH="$QT_HOST_DIR" \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE"

# ----- Build -----
echo ""
echo "===== Building WASM ====="
cmake --build "$BUILD_DIR" --parallel

# ----- Copy to GUIs/ -----
echo ""
echo "===== Copying WASM output to GUIs/ ====="

mkdir -p "$SCRIPT_DIR/GUIs"

if [ ! -f "$BUILD_DIR/myqtwasmservice.wasm" ]; then
    echo "ERROR: myqtwasmservice.wasm not found in $BUILD_DIR"
    echo "       Check build output above for errors."
    exit 1
fi

cp "$BUILD_DIR/myqtwasmservice.wasm" "$SCRIPT_DIR/GUIs/"
echo "  Copied myqtwasmservice.wasm"
cp "$BUILD_DIR/myqtwasmservice.js" "$SCRIPT_DIR/GUIs/"
echo "  Copied myqtwasmservice.js"

# ----- Summary -----
echo ""
echo "===== WASM build complete ====="
echo ""
echo "  Output: GUIs/"
echo "    myqtwasmservice.wasm"
echo "    myqtwasmservice.js"
echo ""
echo "  To test in browser:"
echo "    python -m http.server --directory GUIs/"
echo ""
