#!/bin/bash
# Build DevAtServGUI package for Linux
# Usage: ./build.sh [--pack]
#   --pack  Build unpacked directory only (faster, for testing)
#   (default) Build AppImage + deb

set -e
cd "$(dirname "$0")"

# --- Configurable Python path (edit here or set before calling) ---
: "${PYTHON_PATH:=python3}"

echo "[1/3] Checking prerequisites..."
command -v node >/dev/null 2>&1 || { echo "ERROR: Node.js not found in PATH"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm not found in PATH"; exit 1; }

echo "[2/3] Installing dependencies..."
if [ ! -d node_modules ]; then
    npm install
fi

echo "[3/4] Building MicroserviceBase wheel..."
if command -v "$PYTHON_PATH" >/dev/null 2>&1 || [ -x "$PYTHON_PATH" ]; then
    SKIP_DOCBUILD=1 "$PYTHON_PATH" -m pip wheel --no-deps \
        -w "$(pwd)/build-resources/installers" \
        "$(pwd)/../.." \
    && echo "Wheel built to build-resources/installers/" \
    || echo "WARNING: Wheel build failed, installer will fall back to PyPI"
else
    echo "WARNING: Python not found at $PYTHON_PATH, skipping wheel build"
fi

echo "[4/4] Building..."
if [ "$1" = "--pack" ]; then
    echo "Building unpacked directory..."
    npx electron-builder --dir
else
    echo "Building Linux packages..."
    npx electron-builder --linux
fi

echo ""
echo "Build complete. Output in dist/"
