# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0006.py — L1 static: Python monorepo (project=Toolbox; services=Calculator, Echo).

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
        language="python",
        layout="monorepo",
        services=services,
    )

    out_dir, files = write_scaffold(spec)
    try:
        produced = set(files.keys())
        # one shared .proto, per-service src tree, per-service deploy bits
        expected = {
            "README.md",
            "pyproject.toml",
            "scripts/generate_protos.py",
            "proto/__init__.py",
            "proto/toolbox.proto",
            "src/toolbox/__init__.py",
            # Calculator
            "src/toolbox/calculator/__init__.py",
            "src/toolbox/calculator/main.py",
            "src/toolbox/calculator/config.py",
            "src/toolbox/calculator/context.py",
            "src/toolbox/calculator/domain/__init__.py",
            "src/toolbox/calculator/domain/calculator.py",
            "src/toolbox/calculator/adapters/__init__.py",
            "src/toolbox/calculator/adapters/api/__init__.py",
            "src/toolbox/calculator/adapters/api/grpc_adapter.py",
            # Echo
            "src/toolbox/echo/main.py",
            "src/toolbox/echo/domain/echo.py",
            "src/toolbox/echo/adapters/api/grpc_adapter.py",
            # Per-service deploy
            "deploy/calculator.nomad.hcl",
            "deploy/calculator_service_config.json",
            "deploy/echo.nomad.hcl",
            "deploy/echo_service_config.json",
        }
        missing = sorted(expected - produced)
        if missing:
            return f"FAIL: missing files: {missing}"

        # shared .proto declares both services
        proto = files["proto/toolbox.proto"]
        if "service Calculator" not in proto:
            return "FAIL: shared toolbox.proto missing `service Calculator`"
        if "service Echo" not in proto:
            return "FAIL: shared toolbox.proto missing `service Echo`"

        return "OK: monorepo emitted per-service src trees, shared proto, per-service deploy"

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
