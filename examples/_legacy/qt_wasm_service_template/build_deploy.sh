#!/usr/bin/env bash
# ===================================================================
# build_deploy.sh — Build MyQtWasmService backend and collect
#                   executable and runtime libraries into deploy/
# ===================================================================
#
# Usage:
#   ./build_deploy.sh              Build Release (default)
#   ./build_deploy.sh debug        Build Debug
#   ./build_deploy.sh clean        Delete build + deploy folders
#
# Prerequisites:
#   - vcpkg with librabbitmq and nlohmann-json installed
#     (or system packages: librabbitmq-dev, nlohmann-json3-dev)
#   - CMake 3.21+ and a C++17 compiler
#   - CppServiceBase library built (../cpp_service_base/build/)
#
# Output:
#   deploy/
#   ├── MyQtWasmService             Backend service
#   ├── service_config.json          Service configuration
#   ├── GUIs/                        WASM artifacts for web deployment
#   ├── lib/                         Runtime shared libraries
#   └── run_service.sh               Launcher with LD_LIBRARY_PATH
# ===================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ----- Configurable paths -----
# Auto-detect vcpkg root from CMakePresets.json
if [ -z "${VCPKG_ROOT:-}" ]; then
    if [ -f "$SCRIPT_DIR/CMakePresets.json" ]; then
        tc=$(grep -oP '"toolchainFile"\s*:\s*"\K[^"]+' "$SCRIPT_DIR/CMakePresets.json" 2>/dev/null || true)
        if [ -n "$tc" ]; then
            VCPKG_ROOT="$(dirname "$(dirname "$(dirname "$tc")")")"
        fi
    fi
    : "${VCPKG_ROOT:=$HOME/vcpkg}"
fi

VCPKG_TOOLCHAIN="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake"

# ----- Parse arguments -----
BUILD_TYPE="Release"
PRESET="release"

case "${1:-}" in
    debug|Debug)
        BUILD_TYPE="Debug"
        PRESET="default"
        ;;
    clean)
        echo "Cleaning build and deploy folders..."
        rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/deploy"
        echo "Done."
        exit 0
        ;;
esac

BUILD_DIR="$SCRIPT_DIR/build/$PRESET"
DEPLOY_DIR="$SCRIPT_DIR/deploy"

# ----- Validate prerequisites -----
if ! command -v cmake &>/dev/null; then
    echo "ERROR: cmake not found. Install CMake 3.21+."
    exit 1
fi

echo "Using CMake $(cmake --version | head -1 | awk '{print $3}')"

if [ ! -f "$VCPKG_TOOLCHAIN" ]; then
    echo "WARNING: vcpkg toolchain not found at $VCPKG_TOOLCHAIN"
    echo "         Trying system packages (librabbitmq-dev, nlohmann-json3-dev)..."
fi

# ----- Configure -----
echo ""
echo "===== Configuring CMake [$BUILD_TYPE] ====="

if [ -f "$VCPKG_TOOLCHAIN" ]; then
    cmake --preset "$PRESET" "$SCRIPT_DIR"
else
    mkdir -p "$BUILD_DIR"
    cmake -S "$SCRIPT_DIR" -B "$BUILD_DIR" \
        -DCMAKE_BUILD_TYPE="$BUILD_TYPE"
fi

# ----- Build -----
echo ""
echo "===== Building ====="
cmake --build "$BUILD_DIR" --config "$BUILD_TYPE"

# ----- Deploy -----
echo ""
echo "===== Deploying to $DEPLOY_DIR ====="

rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR" "$DEPLOY_DIR/lib"

# Copy backend executable
if [ -f "$BUILD_DIR/MyQtWasmService" ]; then
    cp "$BUILD_DIR/MyQtWasmService" "$DEPLOY_DIR/"
    echo "  Copied MyQtWasmService"
else
    echo "  WARNING: MyQtWasmService not found — build may have failed"
fi

# Copy service config
if [ -f "$SCRIPT_DIR/service_config.json" ]; then
    cp "$SCRIPT_DIR/service_config.json" "$DEPLOY_DIR/"
    echo "  Copied service_config.json"
fi

# Copy GUIs folder
if [ -d "$SCRIPT_DIR/GUIs" ]; then
    cp -r "$SCRIPT_DIR/GUIs" "$DEPLOY_DIR/GUIs"
    echo "  Copied GUIs/"
fi

# ----- Collect shared library dependencies -----
echo ""
echo "===== Collecting runtime libraries ====="

# Determine vcpkg lib directory
VCPKG_LIB_DIR=""
if [ -d "$VCPKG_ROOT/installed/x64-linux/lib" ]; then
    VCPKG_LIB_DIR="$VCPKG_ROOT/installed/x64-linux/lib"
elif [ -d "$VCPKG_ROOT/installed/x64-osx/lib" ]; then
    VCPKG_LIB_DIR="$VCPKG_ROOT/installed/x64-osx/lib"
fi

# Copy rabbitmq-c shared libraries
if [ -n "$VCPKG_LIB_DIR" ]; then
    for lib in "$VCPKG_LIB_DIR"/librabbitmq*; do
        [ -f "$lib" ] && cp -L "$lib" "$DEPLOY_DIR/lib/" && echo "  $(basename "$lib")"
    done
else
    # Try system library
    for lib in /usr/lib/x86_64-linux-gnu/librabbitmq* /usr/local/lib/librabbitmq*; do
        [ -f "$lib" ] && cp -L "$lib" "$DEPLOY_DIR/lib/" && echo "  $(basename "$lib")"
    done
fi

# Create launcher script with LD_LIBRARY_PATH
cat > "$DEPLOY_DIR/run_service.sh" << 'LAUNCHER'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export LD_LIBRARY_PATH="$DIR/lib:${LD_LIBRARY_PATH:-}"
exec "$DIR/MyQtWasmService" "$@"
LAUNCHER
chmod +x "$DEPLOY_DIR/run_service.sh"
echo "  Created run_service.sh"

# ----- Summary -----
echo ""
echo "===== Build complete ====="
echo ""
echo "  Build type:  $BUILD_TYPE"
echo "  Output:      $DEPLOY_DIR"
echo ""
echo "  To run the backend:"
echo "    cd $DEPLOY_DIR"
echo "    ./run_service.sh"
echo ""
echo "  To build and test the WASM GUI:"
echo "    ./build_wasm.sh       # build WASM binary"
echo "    serve.bat             # start local HTTP server (Windows)"
echo "    python -m http.server # start local HTTP server (Linux)"
echo ""
