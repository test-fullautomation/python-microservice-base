#!/usr/bin/env python3
"""Generate Python gRPC stubs from the hello service proto file.

Writes ``hello_pb2.py`` and ``hello_pb2_grpc.py`` into the ``proto/`` folder
next to the source ``.proto``.  Run once after checkout and again whenever
you edit ``proto/hello.proto``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
PROTO_DIR = SERVICE_ROOT / "proto"


def main() -> int:
    proto_file = PROTO_DIR / "hello.proto"
    if not proto_file.exists():
        print(f"ERROR: {proto_file} not found", file=sys.stderr)
        return 1

    cmd = [
        sys.executable, "-m", "grpc_tools.protoc",
        f"-I{PROTO_DIR}",
        f"--python_out={PROTO_DIR}",
        f"--grpc_python_out={PROTO_DIR}",
        str(proto_file),
    ]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return result.returncode

    # grpc_tools emits ``import hello_pb2`` without the package prefix.
    # Patch the generated grpc stub so it uses a relative import instead.
    grpc_stub = PROTO_DIR / "hello_pb2_grpc.py"
    if grpc_stub.exists():
        text = grpc_stub.read_text(encoding="utf-8")
        patched = text.replace(
            "import hello_pb2 as hello__pb2",
            "from . import hello_pb2 as hello__pb2",
        )
        if patched != text:
            grpc_stub.write_text(patched, encoding="utf-8")
            print("Patched hello_pb2_grpc.py import to use package-relative path")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
