# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0015.py — L2 syntactic: C++ monorepo — shared .proto parses cleanly.

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_service, make_spec, write_scaffold
from testutils.build_helpers    import run_protoc_parse


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

    out_dir, _files = write_scaffold(spec)
    try:
        proto_dir = os.path.join(out_dir, "proto")
        code = run_protoc_parse(proto_dir, [os.path.join(proto_dir, "toolbox.proto")])
        if code == 127:
            return "SKIPPED: grpcio-tools not installed"
        if code != 0:
            return f"FAIL: protoc parse returned {code} for toolbox.proto"
        return "OK: C++ monorepo toolbox.proto parses cleanly (both services in one file)"
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
