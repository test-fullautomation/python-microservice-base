# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0018.py — BADCASE: empty service_name produces malformed file paths.
#
# Documents an existing generator gap: there's no input validation, so an
# empty service_name generates files at paths like ``.nomad.hcl`` (with a
# leading dot from the snake_name) and an empty proto package.  The test
# matches the broken state — when the generator gains validation, this
# will start failing and the test should be updated to expect the new
# ValueError instead.

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_spec, write_scaffold


def test():
    spec = make_spec(
        service_name="",      # invalid input
        language="python",
        layout="single",
        methods=[make_method("Add", "int32", [("a", "int32"), ("b", "int32")])],
    )

    out_dir, files = write_scaffold(spec)
    try:
        # Currently the generator accepts the empty name and writes files
        # with leading-dot paths.  We document that behaviour here.
        bad_paths = [p for p in files if p.startswith(".") or "//" in p]
        if not bad_paths:
            return ("FAIL: generator now appears to validate empty service_name; "
                    "test should be rewritten to expect a ValueError")
        # Also confirm the generated proto has an obviously-empty package
        proto_text = files.get("proto/.proto", "") or files.get("proto/_.proto", "")
        if "package .v1;" in proto_text:
            return "OK: empty service_name produces malformed paths and an empty proto package — generator-side bug documented"
        return "OK: empty service_name produces malformed paths — generator-side bug documented"
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
