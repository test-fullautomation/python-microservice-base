# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0007.py — L2 syntactic: Python monorepo compiles + shared .proto compiles.

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_service, make_spec, write_scaffold
from testutils.build_helpers    import py_compile_tree, run_protoc_python


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

    out_dir, _files = write_scaffold(spec)
    try:
        ok, errors = py_compile_tree(out_dir)
        if errors:
            err_summary = "; ".join(f"{p}: {ex}" for p, ex in errors[:3])
            return f"FAIL: py_compile errors ({len(errors)}): {err_summary}"

        proto_dir = os.path.join(out_dir, "proto")
        gen_dir   = os.path.join(out_dir, "_protoc_out")
        generated, code = run_protoc_python(proto_dir, gen_dir)
        if code == 127:
            return "SKIPPED: grpcio-tools not installed in this Python"
        if code != 0:
            return f"FAIL: protoc returned non-zero ({code})"
        if "toolbox_pb2.py" not in generated or "toolbox_pb2_grpc.py" not in generated:
            return f"FAIL: protoc did not emit expected stubs (got {generated})"

        return "OK: monorepo .py compiled clean; protoc emitted toolbox_pb2.py + toolbox_pb2_grpc.py"

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
