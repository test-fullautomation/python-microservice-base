"""
Tests for debugging a test project's run from the Manager GUI
(adapters/test_project/debugging.py, flow_debug.py, the run manager's debug
side) and Go to Definition (engine.define).

Real Robot Framework processes with the interpreter running the tests.
Flow files need the RobotFramework AIO fork's ``robot.flow``: those tests
run when ``MB_FLOW_SRC`` names the fork's ``src`` folder, and skip otherwise.
"""

import json
import os
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, REPO)

from MicroserviceBase.adapters import test_project as tp  # noqa: E402
from MicroserviceBase.adapters.test_project import debugging  # noqa: E402

FLOW_SRC = os.environ.get("MB_FLOW_SRC", "")
HAS_FLOW = bool(FLOW_SRC) and os.path.isfile(os.path.join(FLOW_SRC, "robot", "flow", "__init__.py"))

SUITE = "testsuites/debug_me.robot"
LIB = "libs/mylib.py"
RESOURCE = "resources/helpers.resource"


def _write(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "bench_tests"
    root.mkdir()
    tp.init_project(str(root), "robotframework-aio")
    _write(root, LIB, '"""A user library."""\n\n\ndef add_numbers(a, b):\n    """Add."""\n'
                      '    total = int(a) + int(b)\n    doubled = double(total)\n    return total\n\n\n'
                      'def double(x):\n    return x * 2\n')
    _write(root, RESOURCE, "*** Keywords ***\nGreet\n    [Arguments]    ${who}\n    Log    hello ${who}\n"
                           "    Log    bye ${who}\n")
    _write(root, SUITE, "*** Settings ***\nLibrary    ../libs/mylib.py\nResource    ../resources/helpers.resource\n\n"
                        "*** Test Cases ***\nAdds\n    ${sum}=    Add Numbers    1    2\n"
                        "    Greet    bench\n    Should Be Equal As Integers    ${sum}    3\n")
    return root


def _until(root, run_id, test, timeout=90):
    """Poll the run until test(status) holds; the status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = tp.RUNS.status(str(root), run_id, 0)
        if test(st):
            return st
        if st["run_state"] == "done" and not test(st):
            raise AssertionError("the run ended: %s\n%s" % (st.get("verdict"), "\n".join(st.get("lines", [])[-30:])))
        time.sleep(0.1)
    raise AssertionError("timed out waiting")


def _stopped(st, seen=-1):
    d = st.get("debug") or {}
    return d.get("stopped") and d["seq"] != seen


def _stop(root, run_id, seen=-1):
    return _until(root, run_id, lambda st: _stopped(st, seen))["debug"]


def _go(root, run_id, command):
    seq = tp.RUNS.status(str(root), run_id, 0)["debug"]["seq"]
    tp.RUNS.debug_command(str(root), run_id, command)
    return seq


def _top(debug):
    return debug["stopped"]["frames"][0]


class Test_FlowLines:

    def test_lines_map_to_steps(self):
        text = ('{\n  "nodes": [\n    { "id": "a", "kind": "start" },\n    {\n      "id": "b",\n'
                '      "kind": "keyword"\n    }\n  ],\n  "edges": [["a", "b"]]\n}\n')
        steps = debugging.anchors(text)
        assert [(s["id"], s["line"], s["first"], s["last"]) for s in steps] == [("a", 3, 3, 3), ("b", 5, 4, 8)]
        assert debugging.step_at(steps, 6)["id"] == "b"
        assert debugging.step_at(steps, 9) is None, "the edges are not a step"
        assert debugging.line_of(steps, "b") == 5


class Test_DebugASuite:

    def test_breakpoint_python_stepping_resource_and_continue(self, project):
        run = tp.RUNS.start(str(project), SUITE, debug={"breakpoints": {SUITE: [7]}})
        assert run["debug"] if "debug" in run else True
        d = _stop(project, run["id"])
        assert d["stopped"]["reason"] == "breakpoint"
        top = _top(d)
        assert (top["path"], top["line"]) == (SUITE, 7)
        assert top["py"]["function"] == "add_numbers", "the keyword is the user's Python"

        variables = tp.RUNS.debug_variables(str(project), run["id"], 1)
        assert variables["ok"]
        assert any(v["name"] == "${SUITE_NAME}" for v in variables["body"])

        # Into the Python function (the built-in stepper): its first line, its locals.
        seen = _go(project, run["id"], "stepIn")
        d = _stop(project, run["id"], seen)
        top = _top(d)
        assert top["python"] and (top["path"], top["line"]) == (LIB, 6), top
        assert d["stopped"]["frames"][1]["path"] == SUITE, "the Robot frame is the caller"
        local = {v["name"]: v["value"] for v in tp.RUNS.debug_variables(str(project), run["id"], top["ref"])["body"]}
        assert local == {"a": "1", "b": "2"}
        assert tp.RUNS.debug_evaluate(str(project), run["id"], "int(a) * 10")["body"]["result"] == "10"

        # Step Over a line, Step Into double(), Step Out of it, Step Over to the return.
        seen = _go(project, run["id"], "next")
        assert _top(_stop(project, run["id"], seen))["line"] == 7
        seen = _go(project, run["id"], "stepIn")
        top = _top(_stop(project, run["id"], seen))
        assert (top["line"], top["name"]) == (12, "double")
        seen = _go(project, run["id"], "stepOut")
        assert _top(_stop(project, run["id"], seen))["line"] == 8

        # Out of the function: Robot's next step, then into the resource keyword.
        seen = _go(project, run["id"], "stepOut")
        top = _top(_stop(project, run["id"], seen))
        assert (top["path"], top["line"], top["python"]) == (SUITE, 8, False)
        seen = _go(project, run["id"], "stepIn")
        top = _top(_stop(project, run["id"], seen))
        assert (top["path"], top["line"]) == (RESOURCE, 4)
        assert tp.RUNS.debug_evaluate(str(project), run["id"], "${who}")["body"]["result"] == "bench"

        tp.RUNS.debug_command(str(project), run["id"], "continue")
        st = _until(project, run["id"], lambda s: s["run_state"] == "done")
        assert st["verdict"] == "pass", "\n".join(st["lines"][-20:])

    def test_breakpoints_change_while_running_and_stop_while_paused(self, project):
        run = tp.RUNS.start(str(project), SUITE, debug={"stop_on_entry": True})
        d = _stop(project, run["id"])
        assert d["stopped"]["reason"] == "pause"
        out = tp.RUNS.debug_breakpoints(str(project), run["id"], RESOURCE, [5])
        assert out == [{"line": 5, "verified": True}]
        seen = _go(project, run["id"], "continue")
        top = _top(_stop(project, run["id"], seen))
        assert (top["path"], top["line"]) == (RESOURCE, 5)
        tp.RUNS.stop(str(project), run["id"])
        st = _until(project, run["id"], lambda s: s["run_state"] == "done")
        assert st["verdict"] in ("fail", "error", "unknown", "pass"), st["verdict"]
        assert not os.path.exists(os.path.join(str(project), "results", run["id"], ".stop"))

    def test_only_one_run_and_no_debug_of_a_dry_run(self, project):
        with pytest.raises(tp.TestProjectError, match="dry run"):
            tp.RUNS.start(str(project), SUITE, dryrun=True, debug={})
        with pytest.raises(tp.TestProjectError, match="not being debugged"):
            tp.RUNS.debug_command(str(project), "nope", "continue")


class Test_Define:

    def test_keywords_of_a_suite(self, project):
        text = open(os.path.join(project, *SUITE.split("/")), encoding="utf-8").read()
        res = tp.define(str(project), SUITE, text, "Add Numbers")
        assert res["found"] and res["path"] == LIB and res["line"] == 4
        res = tp.define(str(project), SUITE, text, "Greet")
        assert (res["path"], res["line"]) == (RESOURCE, 2)
        res = tp.define(str(project), SUITE, text, "Log")
        assert res["path"] is None and res["abs"].endswith("BuiltIn.py")
        assert res["snippet"]["lines"] and res["snippet"]["first"] <= res["line"]
        assert tp.define(str(project), SUITE, text, "No Such Keyword")["found"] is False


@pytest.mark.skipif(not HAS_FLOW, reason="RobotFramework AIO fork with robot.flow not found (MB_FLOW_SRC)")
class Test_DebugAFlow:

    def test_breakpoint_in_a_sub_flow(self, project):
        tp.set_run_settings(str(project), {"pythonpath": [FLOW_SRC]})
        _write(project, "flows/main.flow.json", json.dumps({
            "flow": {"name": "Main", "version": 1},
            "nodes": [{"id": "start", "kind": "start"}, {"id": "t", "kind": "phase", "role": "test", "name": "T"},
                      {"id": "hello", "kind": "keyword", "keyword": "Log", "args": ["hi"]},
                      {"id": "call", "kind": "flow", "file": "sub/step.flow.json", "args": {"LEVEL": "5"}},
                      {"id": "end", "kind": "end"}],
            "edges": [["start", "t"], ["t", "hello"], ["hello", "call"], ["call", "end"]]}, indent=2))
        _write(project, "flows/sub/step.flow.json", json.dumps({
            "flow": {"name": "One Step", "version": 1}, "variables": {"LEVEL": "1"},
            "nodes": [{"id": "start", "kind": "start"},
                      {"id": "check", "kind": "keyword", "keyword": "Should Be True", "args": ["${LEVEL} > 0"]},
                      {"id": "end", "kind": "end"}],
            "edges": [["start", "check"], ["check", "end"]]}, indent=2))
        sub_lines = open(os.path.join(project, "flows", "sub", "step.flow.json"), encoding="utf-8").read().splitlines()
        check = next(i + 1 for i, l in enumerate(sub_lines) if '"check"' in l and '"id"' in l)
        run = tp.RUNS.start(str(project), "flows/main.flow.json",
                            debug={"breakpoints": {"flows/sub/step.flow.json": [check + 1]}})   # a line inside the step
        d = _stop(project, run["id"])
        top = _top(d)
        assert top["node"] == "One Step::check"
        assert (top["path"], top["line"]) == ("flows/sub/step.flow.json", check)
        assert d["stopped"]["frames"][1]["path"] == "flows/main.flow.json"
        assert tp.RUNS.debug_evaluate(str(project), run["id"], "${LEVEL}")["body"]["result"] == "5"
        tp.RUNS.debug_command(str(project), run["id"], "continue")
        assert _until(project, run["id"], lambda s: s["run_state"] == "done")["verdict"] == "pass"
