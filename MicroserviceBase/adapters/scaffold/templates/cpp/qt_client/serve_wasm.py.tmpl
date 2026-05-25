#!/usr/bin/env python3
"""Serve a WASM build directory with COOP/COEP headers.

Multi-threaded Qt WASM uses Web Workers + SharedArrayBuffer.  Browsers
gate SharedArrayBuffer behind cross-origin isolation:

    Cross-Origin-Opener-Policy: same-origin
    Cross-Origin-Embedder-Policy: require-corp

Without these the page loads but Qt's threading bootstrap aborts (the
WASM module hangs at startup with no visible error).  Python's stock
``http.server`` doesn't set them; this thin subclass does.

Run from the qt_client/ directory:
    python serve_wasm.py                # serves ./build-wasm on :8000
    python serve_wasm.py build-wasm     # explicit dir
    PORT=9000 python serve_wasm.py      # override port
"""
from __future__ import annotations

import http.server
import os
import socketserver
import sys
from functools import partial


class COOPCOEPHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()


def main(argv: list[str]) -> int:
    directory = argv[1] if len(argv) > 1 else "build-wasm"
    port = int(os.environ.get("PORT", "8000"))

    if not os.path.isdir(directory):
        print(
            f"ERROR: {directory!r} not found — build first with "
            "build_wasm.bat / build_wasm.sh",
            file=sys.stderr,
        )
        return 1

    handler = partial(COOPCOEPHandler, directory=directory)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Serving {directory!r} at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
        print("COOP/COEP headers enabled — SharedArrayBuffer will work.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
