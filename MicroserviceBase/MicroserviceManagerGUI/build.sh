#!/bin/bash
# Build DevAtServGUI package for Linux
# Usage: ./build.sh [--pack]
#   --pack  Build unpacked directory only (faster, for testing)
#   (default) Build AppImage + deb

set -e
cd "$(dirname "$0")"

echo "[1/3] Checking prerequisites..."
command -v node >/dev/null 2>&1 || { echo "ERROR: Node.js not found in PATH"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm not found in PATH"; exit 1; }

echo "[2/3] Installing dependencies..."
if [ ! -d node_modules ]; then
    npm install
fi

echo "[3/3] Building..."
if [ "$1" = "--pack" ]; then
    echo "Building unpacked directory..."
    npx electron-builder --dir
else
    echo "Building Linux packages..."
    npx electron-builder --linux
fi

echo ""
echo "Build complete. Output in dist/"
