# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0021.py — L1 unit: robot_tmpl.generate_robot_resources emits one .resource
#   per service with prefixed keyword names, ${conn_name} as first positional
#   arg, and Connect/Disconnect helpers that call QConnectBase.

import os, sys, tempfile, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from MicroserviceBase.adapters.scaffold.robot_tmpl import (
    RobotGenError, generate_robot_resources,
)


_PROTO_SRC = '''syntax = "proto3";
package toolbox.v1;

// Exercises three categories the emitter must handle without collisions:
//   * "Connect" RPC name — must not clash with the boilerplate
//     "<Service> Open Connection" helper (renamed for this reason).
//   * Mixed underscore + camelCase in method names — must produce
//     SINGLE-space keyword names, never double (Robot's keyword parser
//     treats 2+ spaces as a delimiter and truncates the name).
service Calculator {
    rpc Add (AddReq) returns (AddResp);
    rpc Ping (Empty) returns (PingResp);
    rpc Connect (Empty) returns (PingResp);
    rpc Get_SubItem_ID (Empty) returns (PingResp);
}

service Echo {
    rpc Say (SayReq) returns (SayResp);
}

message AddReq  { int32 a = 1; int32 b = 2; }
message AddResp { int32 result = 1; }
message Empty   {}
message PingResp { bool ok = 1; }
message SayReq  { string text = 1; }
message SayResp { string echoed = 1; }
'''


def test():
    tmpdir = tempfile.mkdtemp(prefix="msb0021_")
    try:
        proto_path = os.path.join(tmpdir, "toolbox.proto")
        with open(proto_path, "w", encoding="utf-8") as fh:
            fh.write(_PROTO_SRC)

        # --- generate ---------------------------------------------------------
        try:
            files = generate_robot_resources(tmpdir)
        except RobotGenError as exc:
            return f"FAIL: generator raised: {exc}"

        # --- 1. One resource per service, named after the snake-cased class ---
        expected_keys = {"calculator.resource", "echo.resource"}
        actual_keys = set(files.keys())
        if actual_keys != expected_keys:
            return f"FAIL: expected resources {sorted(expected_keys)}, got {sorted(actual_keys)}"

        calc = files["calculator.resource"]
        echo = files["echo.resource"]

        # --- 2. Standard preamble + per-service Open/Close Connection ----------
        # The helpers used to be "Connect" / "Disconnect" but those names
        # collide with proto-defined Connect()/Disconnect() RPCs (e.g.
        # ComSetupDeviceService).  Renamed to "Open Connection" /
        # "Close Connection" so the helper can never clash with an RPC.
        for name, content in (("Calculator", calc), ("Echo", echo)):
            if "Library           QConnectBase.ConnectionManager" not in content:
                return f"FAIL: {name} resource missing QConnectBase Library import"
            if f"{name} Open Connection" not in content:
                return f"FAIL: {name} resource missing '{name} Open Connection' helper"
            if f"{name} Close Connection" not in content:
                return f"FAIL: {name} resource missing '{name} Close Connection' helper"

        # --- 3. Keyword names are PREFIXED with the service name --------------
        if "Calculator Add\n" not in calc.replace("\r\n", "\n"):
            return "FAIL: Calculator resource missing 'Calculator Add' keyword (prefixed)"
        if "Calculator Ping\n" not in calc.replace("\r\n", "\n"):
            return "FAIL: Calculator resource missing 'Calculator Ping' keyword (prefixed)"
        if "Echo Say\n" not in echo.replace("\r\n", "\n"):
            return "FAIL: Echo resource missing 'Echo Say' keyword (prefixed)"

        # --- 4. RPC named 'Connect' must NOT collide with the Open Connection
        #        helper (regression: see ComSetupDeviceService.Connect) ---------
        if "Calculator Connect\n" not in calc.replace("\r\n", "\n"):
            return "FAIL: Calculator resource missing 'Calculator Connect' RPC keyword"
        # ...and the helper rename means the two coexist.

        # --- 5. Underscore-in-name methods must produce SINGLE spaces ---------
        # Regression: GetSubDeviceType_ListCount used to emit
        # "Get Sub Device Type  List Count" (two spaces), which Robot's
        # parser truncates at the double space → multiple keywords collapse
        # to the same name.  Now the converter dedupes underscores.
        if "Calculator Get Sub Item Id\n" not in calc.replace("\r\n", "\n"):
            return ("FAIL: Calculator Get_SubItem_ID should normalize to "
                    "'Calculator Get Sub Item Id' (single spaces)")
        if "  " in [
            line for line in calc.splitlines() if line.startswith("Calculator ")
        ][0]:  # the first 'Calculator …' header — sanity check no double spaces
            # (Robot's "2+ spaces is delimiter" trap)
            pass
        for line in calc.splitlines():
            if line.startswith("Calculator ") and "  " in line:
                return f"FAIL: double space in keyword header: {line!r}"

        # --- 6. ${conn_name} is the FIRST positional arg ----------------------
        # Look at the Add keyword: should have [Arguments]    ${conn_name}    ${a}    ${b}
        import re
        m = re.search(r"Calculator Add\n.*?\[Arguments\]\s+(\$\{[\w]+\})\s+(\$\{[\w]+\})\s+(\$\{[\w]+\})",
                      calc, re.DOTALL)
        if not m:
            return "FAIL: Calculator Add does not declare 3 positional args"
        if m.group(1) != "${conn_name}":
            return f"FAIL: first arg of 'Calculator Add' is {m.group(1)}, expected ${{conn_name}}"
        if {m.group(2), m.group(3)} != {"${a}", "${b}"}:
            return f"FAIL: Add arg2/3 are {m.group(2)}/{m.group(3)}, expected ${{a}}/${{b}}"

        # --- 7. Empty-request method uses the no-args template (no Evaluate) --
        if "Calculator Ping" not in calc:
            return "FAIL: Calculator Ping missing"
        ping_idx = calc.index("Calculator Ping\n")
        next_kw_idx = calc.find("\nCalculator ", ping_idx + 1)
        if next_kw_idx < 0: next_kw_idx = calc.find("\nEcho ", ping_idx + 1)
        if next_kw_idx < 0: next_kw_idx = len(calc)
        ping_body = calc[ping_idx:next_kw_idx]
        if "Create Dictionary" in ping_body:
            return "FAIL: Calculator Ping (no-arg RPC) shouldn't build an args dict"
        if "Evaluate" in ping_body:
            return "FAIL: Calculator Ping (no-arg RPC) shouldn't call Evaluate"

        # --- 8. The FQN constant is set + referenced --------------------------
        if "${CALCULATOR_FQN}" not in calc or "toolbox.v1.Calculator" not in calc:
            return "FAIL: Calculator FQN constant or value missing"
        if "${ECHO_FQN}" not in echo or "toolbox.v1.Echo" not in echo:
            return "FAIL: Echo FQN constant or value missing"

        n_kw_calc = calc.count("\nCalculator ")
        n_kw_echo = echo.count("\nEcho ")
        return (
            f"OK: 2 resources emitted; Calculator has {n_kw_calc} keywords, "
            f"Echo has {n_kw_echo} keywords; "
            f"prefixed names + conn_name-first + Open/Close Connection helpers + "
            f"no Connect/underscore collisions verified"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
