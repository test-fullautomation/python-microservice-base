# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0016.py — L3 build: C++ single-service CMake configure step.
#
# Skips when cmake isn't on PATH (most dev machines without the C++
# toolchain).  When cmake is present, this catches CMakeLists syntax
# errors and missing find_package() entries — without doing a full
# build (no compiler / vcpkg dependencies needed).

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_spec, write_scaffold
from testutils.build_helpers    import cmake_configure


def test():
    spec = make_spec(
        service_name="Echo",
        language="cpp",
        layout="single",
        methods=[make_method("Say", return_type="string", params=[("text", "string")])],
        gui_type="none",
        client_grpc_kind="google",
        server_grpc_kind="msys2",
    )

    out_dir, _files = write_scaffold(spec)
    try:
        code, log_path = cmake_configure(out_dir)
        if code == 127:
            return "SKIPPED: cmake not on PATH"
        if code != 0:
            tail = ""
            if log_path and os.path.isfile(log_path):
                with open(log_path, encoding="utf-8", errors="replace") as fh:
                    tail = fh.read()[-600:]
            # Without vcpkg / system gRPC the find_package() will fail,
            # which is environmental rather than a generator bug.  Treat
            # missing-package errors as a SKIP so this case stays useful
            # on machines that have cmake but no gRPC install.
            if "Could not find a package configuration file provided by \"gRPC\"" in tail \
               or "Could NOT find Protobuf" in tail \
               or "Could not find a package configuration file provided by \"Protobuf\"" in tail:
                return "SKIPPED: cmake configure cannot find gRPC / Protobuf (no vcpkg or system install)"
            return f"FAIL: cmake configure exit {code}; log tail: {tail!r}"
        return "OK: cmake configure exit 0 for C++ single-service"
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
