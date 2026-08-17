# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0009.py — BADCASE: Python + multi_proto layout is unsupported and must raise NotImplementedError.

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_service, make_spec, write_scaffold


def test():
    services = [
        make_service("Calculator", [make_method("Add", "int32", [("a", "int32"), ("b", "int32")])]),
        make_service("Echo",       [make_method("Say", "string", [("text", "string")])]),
    ]
    spec = make_spec(
        service_name="Toolbox",
        language="python",          # multi_proto is C++-only
        layout="multi_proto",
        services=services,
    )

    # Should raise NotImplementedError before writing any files.  The
    # orchestrator turns the exception into a string and matches it
    # against EXPECTEDEXCEPTION.
    write_scaffold(spec)
    return "FAIL: write_scaffold did not raise NotImplementedError for python+multi_proto"
