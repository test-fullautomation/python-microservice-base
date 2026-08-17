# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0002.py — L2 syntactic: every .py compiles + protoc emits expected stubs.

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_spec, write_scaffold
from testutils.build_helpers    import py_compile_tree, run_protoc_python


def test():
    spec = make_spec(
        service_name="Calculator",
        language="python",
        layout="single",
        methods=[
            make_method("Add",      return_type="int32", params=[("a", "int32"), ("b", "int32")]),
            make_method("Multiply", return_type="int32", params=[("a", "int32"), ("b", "int32")]),
        ],
    )

    out_dir, _files = write_scaffold(spec)
    try:
        # --- py_compile every generated .py --------------------------------------
        ok, errors = py_compile_tree(out_dir)
        if errors:
            err_summary = "; ".join(f"{p}: {ex}" for p, ex in errors[:3])
            return f"FAIL: py_compile errors ({len(errors)}): {err_summary}"
        if ok < 1:
            return f"FAIL: py_compile_tree found 0 .py files under {out_dir}"

        # --- protoc on the generated .proto -------------------------------------
        proto_dir = os.path.join(out_dir, "proto")
        gen_dir   = os.path.join(out_dir, "_protoc_out")
        generated, code = run_protoc_python(proto_dir, gen_dir)
        if code == 127:
            return "SKIPPED: grpcio-tools not installed in this Python (pip install grpcio-tools)"
        if code != 0:
            return f"FAIL: protoc returned non-zero ({code})"
        expected = ["calculator_pb2.py", "calculator_pb2_grpc.py"]
        missing = [f for f in expected if f not in generated]
        if missing:
            return f"FAIL: protoc did not emit expected stubs: {missing} (got {generated})"

        return "OK: py_compile clean; protoc emitted calculator_pb2.py and calculator_pb2_grpc.py"

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
