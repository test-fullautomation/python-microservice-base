# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0005.py — L1 static: C++ multi_proto layout (project="Toolbox", services=[Calculator, Echo]).

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import (
    make_method, make_service, make_spec, write_scaffold,
)


def test():
    services = [
        make_service(
            "Calculator",
            methods=[make_method("Add", return_type="int32", params=[("a", "int32"), ("b", "int32")])],
        ),
        make_service(
            "Echo",
            methods=[make_method("Say", return_type="string", params=[("text", "string")])],
        ),
    ]

    spec = make_spec(
        service_name="Toolbox",
        language="cpp",
        layout="multi_proto",
        services=services,
        gen_nomad=True,
        # keep file count predictable — no GUI / no qt-vcpkg client
        gui_type="none",
        client_grpc_kind="google",
        server_grpc_kind="msys2",
    )

    out_dir, files = write_scaffold(spec)
    try:
        produced = set(files.keys())
        expected_per_service = []
        for svc_pascal, svc_snake in [("Calculator", "calculator"), ("Echo", "echo")]:
            expected_per_service += [
                f"proto/{svc_snake}.proto",
                f"src/{svc_snake}/domain/{svc_pascal}.h",
                f"src/{svc_snake}/domain/{svc_pascal}.cpp",
                f"src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.h",
                f"src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.cpp",
            ]
        expected_shared = [
            "CMakeLists.txt",
            "src/main.cpp",
            "src/Settings.h",
            "proto/generate_stubs.bat",
            "proto/generate_stubs.sh",
            "set_env.bat",
            "set_env.sh",
            "deploy/toolbox.nomad.hcl",
        ]
        for required in expected_per_service + expected_shared:
            if required not in produced:
                return f"FAIL: missing file '{required}' (got {len(produced)} files total)"

        # content markers
        main_cpp = files["src/main.cpp"]
        if "microservice_base::ServiceRunner" not in main_cpp:
            return "FAIL: src/main.cpp does not use microservice_base::ServiceRunner"
        if "runner.addService" not in main_cpp:
            return "FAIL: src/main.cpp does not call runner.addService"
        # multi_proto registers each service by its FQN (package.v1.Name)
        if '"calculator.v1.Calculator"' not in main_cpp:
            return "FAIL: src/main.cpp does not register calculator.v1.Calculator"
        if '"echo.v1.Echo"' not in main_cpp:
            return "FAIL: src/main.cpp does not register echo.v1.Echo"

        cmake = files["CMakeLists.txt"]
        if "find_package(gRPC" not in cmake:
            return "FAIL: CMakeLists.txt missing find_package(gRPC ...)"
        if "gRPC::grpc++" not in cmake:
            return "FAIL: CMakeLists.txt does not link gRPC::grpc++"

        for svc_snake in ("calculator", "echo"):
            proto = files[f"proto/{svc_snake}.proto"]
            if f"package {svc_snake}.v1;" not in proto:
                return f"FAIL: proto/{svc_snake}.proto package declaration wrong"

        return "OK: per-service files present for Calculator + Echo; multi_proto markers verified"

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
