# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0003.py — L3 build: project's own scripts/generate_protos.py runs cleanly.

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_spec, write_scaffold
from testutils.build_helpers    import run_generate_protos_script


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
        code, log_path = run_generate_protos_script(out_dir)
        if code == 2:
            return f"FAIL: scripts/generate_protos.py not found in {out_dir}"
        if code != 0:
            tail = ""
            if log_path and os.path.isfile(log_path):
                with open(log_path, encoding="utf-8", errors="replace") as fh:
                    tail = fh.read()[-400:]
            return f"FAIL: generate_protos.py exit {code}; log tail: {tail!r}"

        proto_dir = os.path.join(out_dir, "proto")
        produced = sorted(os.listdir(proto_dir)) if os.path.isdir(proto_dir) else []
        for required in ("calculator_pb2.py", "calculator_pb2_grpc.py"):
            if required not in produced:
                return f"FAIL: {required} not in proto/ after generate_protos.py (got {produced})"

        return "OK: generate_protos.py exit 0; calculator_pb2.py + calculator_pb2_grpc.py present in proto/"

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
