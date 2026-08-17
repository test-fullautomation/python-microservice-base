# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0008.py — L1 static: C++ single-service layout.

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_spec, write_scaffold


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

    out_dir, files = write_scaffold(spec)
    try:
        produced = set(files.keys())
        expected = {
            "CMakeLists.txt",
            "README.md",
            "echo.nomad.hcl",
            "proto/echo.proto",
            "service_config.json",
            "set_env.bat",
            "set_env.sh",
            "src/Settings.h",
            "src/adapters/api/EchoGrpcAdapter.cpp",
            "src/adapters/api/EchoGrpcAdapter.h",
            "src/domain/EchoService.cpp",
            "src/domain/EchoService.h",
            "src/main.cpp",
        }
        missing = sorted(expected - produced)
        if missing:
            return f"FAIL: missing files: {missing}"

        main_cpp = files["src/main.cpp"]
        if "microservice_base::ServiceRunner" not in main_cpp:
            return "FAIL: src/main.cpp does not use microservice_base::ServiceRunner"
        if "EchoGrpcAdapter" not in main_cpp:
            return "FAIL: src/main.cpp does not reference EchoGrpcAdapter"

        proto = files["proto/echo.proto"]
        if "service EchoService" not in proto:
            return "FAIL: proto/echo.proto missing `service EchoService`"

        cmake = files["CMakeLists.txt"]
        if "find_package(gRPC" not in cmake or "gRPC::grpc++" not in cmake:
            return "FAIL: CMakeLists.txt missing gRPC find_package or link"

        return "OK: C++ single-service emitted CMake + main.cpp + Echo domain/adapter; markers verified"

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
