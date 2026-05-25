# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0020.py — L1 unit: LocalProtoClient._is_excluded prunes build / vendor
#   dirs so a recursive glob doesn't slurp duplicate google.protobuf.* schemas
#   into protoc.
#
# Regression guard for the GUI flow "Reflection unavailable + provide a proto
# folder" where protoc previously exited 1 because every
# ``build*/vcpkg_installed/.../google/protobuf/*.proto`` it could find got
# fed in alongside the user's actual service .proto.

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from MicroserviceBase.adapters.grpc_bridge.reflect_client import LocalProtoClient


def _to_native(p):
    """Convert a forward-slash path to the host's separator so the test
    behaves the same on Windows and POSIX."""
    return p.replace("/", os.sep)


# (path, expected_excluded?, reason)
_CASES = [
    # ---------- KEEP ----------
    ("D:/Project/repo/examples/MultiProto2/proto/com_config_device.proto",
     False, "real service proto under examples/<svc>/proto/"),
    ("D:/Project/repo/examples/MultiProto2/proto/power_device.proto",
     False, "real service proto under examples/<svc>/proto/"),
    ("D:/Project/repo/examples/cpp_hello_service/proto/hello.proto",
     False, "sibling example .proto (intentional — only user override blocks)"),
    ("D:/Project/repo/SampleServices/foo/proto/foo.proto",
     False, "SampleServices fallback"),

    # ---------- SKIP — vcpkg_installed ----------
    ("D:/Project/repo/examples/MultiProto/build-qt-vcpkg/vcpkg_installed/x64-mingw-qt/include/google/protobuf/any.proto",
     True, "vcpkg_installed include — google well-known type"),
    ("D:/Project/repo/examples/MultiProto/qt_client_grpcpp/build/vcpkg_installed/x64-windows/include/google/protobuf/timestamp.proto",
     True, "vcpkg_installed include (host triplet)"),
    ("D:/Project/repo/examples/MultiProto2/build-qt-vcpkg/vcpkg_installed/x64-mingw-qt/include/google/protobuf/descriptor.proto",
     True, "vcpkg_installed include (descriptor.proto)"),

    # ---------- SKIP — build-* / build_* prefix ----------
    ("D:/Project/repo/examples/MultiProto/build-qt-vcpkg/some/proto.proto",
     True, "build-* dir prefix"),
    ("D:/Project/repo/examples/Svc/build-wasm/gen/x.proto",
     True, "build-wasm output dir"),
    ("D:/Project/repo/build_msys2/x.proto",
     True, "build_ prefix variant"),

    # ---------- SKIP — bare build dir ----------
    ("D:/Project/repo/examples/MultiProto/qt_client_grpcpp/build/x.proto",
     True, "bare build/ subdir"),

    # ---------- SKIP — vendor / generated ----------
    ("D:/Project/repo/examples/_legacy/TestService/proto/test_service.proto",
     True, "_legacy folder"),
    ("D:/Project/repo/electron/node_modules/grpc/proto/x.proto",
     True, "node_modules"),
    ("D:/Project/repo/.git/hooks/x.proto",
     True, ".git internals"),
    ("D:/Project/repo/MicroserviceBase/__pycache__/x.proto",
     True, "__pycache__"),
]


def test():
    failures = []
    n_keep = 0
    n_skip = 0
    for raw, expected_excluded, reason in _CASES:
        path = _to_native(raw)
        actual = LocalProtoClient._is_excluded(path)
        if actual != expected_excluded:
            failures.append(
                f"  {raw!r}\n"
                f"    expected excluded={expected_excluded}, got {actual} ({reason})"
            )
        elif expected_excluded:
            n_skip += 1
        else:
            n_keep += 1

    if failures:
        return "FAIL: _is_excluded classifications wrong:\n" + "\n".join(failures)

    return (
        f"OK: _is_excluded correctly kept {n_keep} real-proto paths "
        f"and excluded {n_skip} build/vendor paths"
    )
