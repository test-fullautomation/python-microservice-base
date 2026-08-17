# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0019.py — L1 static: C++ multi_proto + Qt6::Grpc client emits qt_client/
#   with multi-proto-aware CMakeLists + MainWindow.cpp + WASM build/serve scripts.

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import (
    make_method, make_service, make_spec, write_scaffold,
)


def test():
    services = [
        make_service(
            "Calculator",
            methods=[make_method("Add", return_type="int32",
                                 params=[("a", "int32"), ("b", "int32")])],
        ),
        make_service(
            "Echo",
            methods=[make_method("Say", return_type="string",
                                 params=[("text", "string")])],
        ),
    ]

    spec = make_spec(
        service_name="Toolbox",
        language="cpp",
        layout="multi_proto",
        services=services,
        gen_nomad=True,
        gui_type="widget",          # ← gates the qt_client/ emission
        client_grpc_kind="qt",      # ← selects Qt6::Grpc over Google grpc++
        server_grpc_kind="msys2",
    )

    out_dir, files = write_scaffold(spec)
    try:
        # --- 1. qt_client/ skeleton present -----------------------------
        expected_qt_client = [
            "qt_client/CMakeLists.txt",
            "qt_client/proto/calculator.proto",
            "qt_client/proto/echo.proto",
            "qt_client/proto/generate_qt_stubs.bat",
            "qt_client/proto/generate_qt_stubs.sh",
            "qt_client/src/main.cpp",
            "qt_client/src/MainWindow.h",
            "qt_client/src/MainWindow.cpp",
            "qt_client/src/MainWindow.ui",
            "qt_client/build_qt.bat",
            "qt_client/build_qt.sh",
            "qt_client/build_deploy_qt.bat",
            "qt_client/build_deploy_qt.sh",
            "qt_client/build_wasm.bat",
            "qt_client/build_wasm.sh",
            "qt_client/serve_wasm.py",
            "qt_client/serve_wasm.bat",
            "qt_client/serve_wasm.sh",
            "qt_client/README.md",
        ]
        missing = [p for p in expected_qt_client if p not in files]
        if missing:
            return f"FAIL: qt_client/ missing files: {missing}"

        # --- 2. CMakeLists lists BOTH .proto files in PROTO_FILES -------
        cmake = files["qt_client/CMakeLists.txt"]
        if "proto/calculator.proto" not in cmake:
            return "FAIL: qt_client/CMakeLists.txt PROTO_FILES missing calculator.proto"
        if "proto/echo.proto" not in cmake:
            return "FAIL: qt_client/CMakeLists.txt PROTO_FILES missing echo.proto"

        # --- 3. MainWindow.cpp has N include pairs (one per proto) ------
        mw = files["qt_client/src/MainWindow.cpp"]
        for required_inc in (
            'calculator.qpb.h',
            'calculator_client.grpc.qpb.h',
            'echo.qpb.h',
            'echo_client.grpc.qpb.h',
        ):
            if f'#include "{required_inc}"' not in mw:
                return f"FAIL: qt_client/src/MainWindow.cpp missing #include \"{required_inc}\""

        # --- 4. Per-service namespace dispatch (each uses its own ns) ---
        # Auto-generated package = "<snake>.v1", namespace = "<snake>::v1"
        if "calculator::v1::Calculator" not in mw:
            return "FAIL: MainWindow.cpp missing calculator::v1::Calculator client/dispatch"
        if "echo::v1::Echo" not in mw:
            return "FAIL: MainWindow.cpp missing echo::v1::Echo client/dispatch"

        # --- 5. WASM helpers carry the right project exe name ----------
        bat = files["qt_client/build_wasm.bat"]
        if "toolbox_qt_gui.wasm" not in bat:
            return "FAIL: qt_client/build_wasm.bat does not reference toolbox_qt_gui.wasm"
        serve_py = files["qt_client/serve_wasm.py"]
        if "COOPCOEPHandler" not in serve_py:
            return "FAIL: serve_wasm.py missing COOPCOEPHandler"
        if "Cross-Origin-Opener-Policy" not in serve_py:
            return "FAIL: serve_wasm.py does not emit COOP header"
        if "Cross-Origin-Embedder-Policy" not in serve_py:
            return "FAIL: serve_wasm.py does not emit COEP header"

        # --- 6. No leftover @@{...} placeholders anywhere in qt_client/ --
        for path, content in files.items():
            if path.startswith("qt_client/") and "@@{" in content:
                return f"FAIL: leftover placeholder in {path}"

        n = sum(1 for k in files if k.startswith("qt_client/"))
        return f"OK: qt_client/ emitted {n} files; multi-proto CMakeLists + N include pairs + per-service namespaces + WASM scripts verified"

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
