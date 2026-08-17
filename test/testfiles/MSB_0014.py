# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0014.py — L1 static: C++ monorepo (project=Toolbox; services=Calculator, Echo).

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_service, make_spec, write_scaffold


def test():
    services = [
        make_service("Calculator", [make_method("Add", "int32", [("a", "int32"), ("b", "int32")])]),
        make_service("Echo",       [make_method("Say", "string", [("text", "string")])]),
    ]
    spec = make_spec(
        service_name="Toolbox",
        language="cpp",
        layout="monorepo",
        services=services,
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
            "proto/toolbox.proto",
            "proto/generate_stubs.bat",
            "proto/generate_stubs.sh",
            "set_env.bat",
            "set_env.sh",
            # Per-service src trees (one main.cpp + Settings.h + domain + adapter per svc)
            "src/calculator/main.cpp",
            "src/calculator/Settings.h",
            "src/calculator/domain/Calculator.h",
            "src/calculator/domain/Calculator.cpp",
            "src/calculator/adapters/api/CalculatorGrpcAdapter.h",
            "src/calculator/adapters/api/CalculatorGrpcAdapter.cpp",
            "src/echo/main.cpp",
            "src/echo/domain/Echo.h",
            "src/echo/adapters/api/EchoGrpcAdapter.h",
            # Per-service deploy
            "deploy/calculator.nomad.hcl",
            "deploy/calculator_service_config.json",
            "deploy/echo.nomad.hcl",
            "deploy/echo_service_config.json",
        }
        missing = sorted(expected - produced)
        if missing:
            return f"FAIL: missing files: {missing}"

        # Shared .proto declares both services
        proto = files["proto/toolbox.proto"]
        if "service Calculator" not in proto:
            return "FAIL: shared toolbox.proto missing `service Calculator`"
        if "service Echo" not in proto:
            return "FAIL: shared toolbox.proto missing `service Echo`"

        # Each per-service main.cpp uses ServiceRunner
        for sn in ("calculator", "echo"):
            mc = files[f"src/{sn}/main.cpp"]
            if "microservice_base::ServiceRunner" not in mc:
                return f"FAIL: src/{sn}/main.cpp does not use microservice_base::ServiceRunner"

        return "OK: C++ monorepo emitted per-service src trees, shared proto, per-service deploy"

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
