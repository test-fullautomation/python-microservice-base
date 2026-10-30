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

echo "[3/4] Getting the MicroserviceBase and bridge wheels..."
# MSB_SRC: a checkout of the base repo to build MicroserviceBase from;
# without it the version installer.nsh names comes from the package index.
if command -v "$PYTHON_PATH" >/dev/null 2>&1 || [ -x "$PYTHON_PATH" ]; then
    "$PYTHON_PATH" build-resources/fetch_wheels.py \
    || echo "WARNING: wheels missing, the installer will fall back to the package index"
else
    echo "WARNING: Python not found at $PYTHON_PATH, skipping the wheels"
fi

# The wheels' dependencies for the deb's offline install (postinst.sh), for
# each Python a supported distro ships: Ubuntu 22.04/24.04, Debian 12, 3.13.
# WHEELHOUSE_INDEX_URL picks the index when pip's configured one is unreachable.
echo "[3b/4] Downloading the dependency wheels..."
WHEELHOUSE="$(pwd)/build-resources/wheelhouse"
mkdir -p "$WHEELHOUSE"
rm -f "$WHEELHOUSE"/*.whl
MSB_WHEEL="$(ls build-resources/installers/microservicebase-*-py3-none-any.whl 2>/dev/null | head -n1)"
BRIDGE_WHEEL="$(ls build-resources/installers/microservice_gui_bridge-*-py3-none-any.whl 2>/dev/null | head -n1)"
if [ -n "$MSB_WHEEL" ] && [ -n "$BRIDGE_WHEEL" ]; then
    for v in 3.10 3.11 3.12 3.13; do
        "$PYTHON_PATH" -m pip download --quiet --disable-pip-version-check \
            ${WHEELHOUSE_INDEX_URL:+--index-url "$WHEELHOUSE_INDEX_URL"} \
            -d "$WHEELHOUSE" --only-binary=:all: --implementation cp --python-version "$v" \
            --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 \
            --platform manylinux2014_x86_64 --platform linux_x86_64 \
            "$MSB_WHEEL" "$BRIDGE_WHEEL" \
        || echo "WARNING: no dependency wheels for Python $v; the deb downloads them at install time"
    done
    rm -f "$WHEELHOUSE"/microservicebase-*.whl "$WHEELHOUSE"/microservice_gui_bridge-*.whl
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
