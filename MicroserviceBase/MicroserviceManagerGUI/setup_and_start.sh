#!/usr/bin/env bash
# Fresh-PC bootstrap for the MicroserviceManagerGUI.
#
#   1. If system Node.js isn't on PATH, download a portable copy into
#      ./tools/node/ (no root needed) and use it.
#   2. Run `npm install` if node_modules/ is missing.
#   3. Launch the Manager GUI via `npm start`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODE_VERSION="20.18.0"
TOOLS_DIR="$SCRIPT_DIR/tools"
NODE_DIR="$TOOLS_DIR/node"

detect_node_platform() {
    local os arch nodearch
    os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    arch="$(uname -m)"
    case "$arch" in
        x86_64|amd64) nodearch="x64" ;;
        aarch64|arm64) nodearch="arm64" ;;
        armv7l) nodearch="armv7l" ;;
        *) echo "Unsupported CPU: $arch" >&2; exit 1 ;;
    esac
    case "$os" in
        linux)  echo "linux-$nodearch" ;;
        darwin) echo "darwin-$nodearch" ;;
        *) echo "Unsupported OS: $os" >&2; exit 1 ;;
    esac
}

ensure_node() {
    if command -v node >/dev/null 2>&1; then
        echo "[1/3] Using system Node.js."
        return 0
    fi
    if [[ -x "$NODE_DIR/bin/node" ]]; then
        echo "[1/3] Using portable Node.js at $NODE_DIR."
        export PATH="$NODE_DIR/bin:$PATH"
        return 0
    fi

    echo "[1/3] Node.js not found — downloading portable v$NODE_VERSION (~30MB)..."
    local platform tarball url tmp
    platform="$(detect_node_platform)"
    tarball="node-v${NODE_VERSION}-${platform}.tar.xz"
    url="https://nodejs.org/dist/v${NODE_VERSION}/${tarball}"

    mkdir -p "$TOOLS_DIR"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' RETURN

    if command -v curl >/dev/null 2>&1; then
        curl -fL -o "$tmp/node.tar.xz" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$tmp/node.tar.xz" "$url"
    else
        echo "ERROR: need curl or wget to download Node.js." >&2
        exit 1
    fi

    echo "    Extracting..."
    tar -xJf "$tmp/node.tar.xz" -C "$tmp"
    rm -rf "$NODE_DIR"
    mv "$tmp/node-v${NODE_VERSION}-${platform}" "$NODE_DIR"
    export PATH="$NODE_DIR/bin:$PATH"
    echo "    Portable Node.js installed at $NODE_DIR."
}

ensure_node
echo "    node=$(node --version)  npm=$(npm --version)"

if [[ -f "$SCRIPT_DIR/node_modules/electron/package.json" ]]; then
    echo "[2/3] node_modules already present — skipping npm install."
else
    echo "[2/3] Installing npm dependencies (first run only)..."
    ( cd "$SCRIPT_DIR" && npm install )
fi

echo "[3/3] Starting Manager GUI..."
cd "$SCRIPT_DIR"
exec npm start
