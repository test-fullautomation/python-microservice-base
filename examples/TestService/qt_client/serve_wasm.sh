#!/usr/bin/env bash
# Serve the WASM build with COOP/COEP headers required for multi-threaded
# WASM (SharedArrayBuffer).  Plain `python3 -m http.server` will NOT work —
# it serves the files but the WASM module hangs at startup because Qt's
# threading bootstrap can't allocate a SharedArrayBuffer.
#
# Override the port:   PORT=9000 ./serve_wasm.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/serve_wasm.py" "${SCRIPT_DIR}/build-wasm"
