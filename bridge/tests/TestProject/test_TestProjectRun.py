"""
Tests for running a test project's tests (adapters/test_project/runs.py,
the Robot Framework AIO adapter's run side, and the bridge endpoints).

Runs real Robot Framework processes with the interpreter running the
tests. Flow files need the RobotFramework AIO fork's ``robot.flow``; those
tests run when ``MB_FLOW_SRC`` names the fork's ``src`` folder, and skip
otherwise.
"""

import json
import os
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, REPO)

from MicroserviceBase.adapters import test_project as tp  # noqa: E402

pytest.importorskip("robot")

FLOW_SRC = os.environ.get("MB_FLOW_SRC", "")
HAS_FLOW = bool(FLOW_SRC) and os.path.isfile(os.path.join(FLOW_SRC, "robot", "flow", "__init__.py"))

PASSING = """\
*** Variables ***
${WHO}    world

*** Test Cases ***
Greets
    Log To Console    hello ${WHO}

Adds
    Should Be Equal As Integers    ${{1 + 1}}    2
"""

FAILING = """\
*** Test Cases ***
Holds
    No Operation

Breaks
    Fail    the bench said no
"""

SLOW = """\
*** Settings ***
Suite Teardown    Log To Console    teardown ran

*** Test Cases ***
Waits
    Log To Console    waiting
    Sleep    60s
"""

FLOW_UNKNOWN = {
    "flow": {"name": "Gate Times Out", "version": 1},
    "nodes": [
        {"id": "start", "kind": "start"},
        {"id": "wait", "kind": "gate", "keyword": "Should Be Equal", "args": ["a", "b"],
         "timeout": "1s", "interval": "0.2s"},
        {"id": "end", "kind": "end"},
    ],
    "edges": [["start", "wait"], ["wait", "end"]],
}


def _write(root, rel, text):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _wait(root, run_id, timeout=90):
    deadline = time.time() + timeout
    lines, since = [], 0
    while time.time() < deadline:
        st = tp.RUNS.status(str(root), run_id, since)
        lines += st["lines"]
        since = st["next"]
        if st["run_state"] == "done":
            st["all_lines"] = lines
            return st
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "bench_tests"
    root.mkdir()
    tp.init_project(str(root), "robotframework-aio")
    _write(root, "testsuites/passing.robot", PASSING)
    _write(root, "testsuites/failing.robot", FAILING)
    return root


class Test_Tree:

    def test_runnable_files_and_flow_kind(self, project):
        _write(project, "testsuites/plan.flow.json", json.dumps(FLOW_UNKNOWN))
        tree = tp.project_tree(str(project))
        files = {f["path"]: f for f in tree["files"]}
        assert files["testsuites/passing.robot"]["runnable"] is True
        assert files["testsuites/plan.flow.json"]["kind"] == "flow"
        assert files["testsuites/plan.flow.json"]["runnable"] is True
        assert files["testsuites/config/robot_config.jsonp"]["runnable"] is False
        assert files["testproject.json"]["runnable"] is False
        assert tree["can_run"] is True
        assert tree["run_settings"] == {"python": "", "pythonpath": [], "args": [], "env": {}}

    def test_json_syntax_check(self):
        assert tp.check_syntax("a.flow.json", '{"flow": {}}') == []
        problems = tp.check_syntax("a.flow.json", '{\n  "flow": ,\n}')
        assert problems and problems[0]["line"] == 2
        assert problems[0]["message"].startswith("Invalid JSON")


class Test_RunSettings:

    def test_round_trip_and_removal(self, project):
        out = tp.set_run_settings(str(project), {"python": " py ", "pythonpath": ["../src", " "],
                                                 "args": ["--loglevel", "DEBUG"], "env": {"A": "1"}})
        assert out["settings"] == {"python": "py", "pythonpath": ["../src"],
                                   "args": ["--loglevel", "DEBUG"], "env": {"A": "1"}}
        manifest = json.loads((project / "testproject.json").read_text(encoding="utf-8"))
        assert manifest["run"]["pythonpath"] == ["../src"]
        tp.set_run_settings(str(project), {"python": "", "pythonpath": [], "args": [], "env": {}})
        manifest = json.loads((project / "testproject.json").read_text(encoding="utf-8"))
        assert "run" not in manifest

    @pytest.mark.parametrize("bad", [
        {"pythonpath": "src"}, {"args": [1]}, {"python": 3}, {"env": {"A": 1}}, {"shell": "x"},
    ])
    def test_invalid_settings_are_refused(self, project, bad):
        with pytest.raises(tp.TestProjectError):
            tp.set_run_settings(str(project), bad)


class Test_Run:

    def test_passing_suite(self, project):
        run = tp.RUNS.start(str(project), "testsuites/passing.robot")
        assert run["run_state"] == "running"
        st = _wait(project, run["id"])
        assert st["verdict"] == "pass"
        assert st["counts"] == {"pass": 2, "fail": 0, "unknown": 0, "skip": 0}
        assert [t["name"] for t in st["tests"]] == ["Greets", "Adds"]
        assert any("hello world" in line for line in st["all_lines"])
        out_dir = project / "results" / run["id"]
        for name in ("log.html", "report.html", "output.xml", "console.log", "run.json"):
            assert (out_dir / name).is_file(), name
        assert not (out_dir / ".stop").exists()
        assert st["artifacts"][0] == {"name": "log.html", "label": "Log", "primary": True}

    def test_failing_suite_and_message(self, project):
        st = _wait(project, tp.RUNS.start(str(project), "testsuites/failing.robot")["id"])
        assert st["verdict"] == "fail"
        assert st["counts"]["pass"] == 1 and st["counts"]["fail"] == 1
        broken = [t for t in st["tests"] if t["name"] == "Breaks"][0]
        assert broken["status"] == "fail" and broken["message"] == "the bench said no"

    def test_variables_and_dryrun(self, project):
        st = _wait(project, tp.RUNS.start(str(project), "testsuites/passing.robot",
                                          variables={"WHO": "bench"})["id"])
        assert any("hello bench" in line for line in st["all_lines"])
        assert "--variable" in st["argv"] and "WHO:bench" in st["argv"]
        dry = _wait(project, tp.RUNS.start(str(project), "testsuites/failing.robot", dryrun=True)["id"])
        assert dry["verdict"] == "pass"     # Fail is not executed in a dry run
        assert "--dryrun" in dry["argv"]

    def test_invalid_variable_name(self, project):
        with pytest.raises(tp.TestProjectError, match="Invalid variable name"):
            tp.RUNS.start(str(project), "testsuites/passing.robot", variables={"A B": "1"})

    def test_whole_project(self, project):
        st = _wait(project, tp.RUNS.start(str(project), "")["id"])
        assert st["target_label"].startswith("testsuites")
        assert st["verdict"] == "fail"
        assert st["counts"]["pass"] == 3 and st["counts"]["fail"] == 1
        assert {t["suite"] for t in st["tests"]} == {"Testsuites.Failing", "Testsuites.Passing"}

    def test_not_runnable_and_escape(self, project):
        with pytest.raises(tp.TestProjectError, match="cannot run"):
            tp.RUNS.start(str(project), "testsuites/config/robot_config.jsonp")
        with pytest.raises(tp.TestProjectError, match="escapes"):
            tp.RUNS.start(str(project), "../elsewhere.robot")

    def test_missing_interpreter(self, project):
        tp.set_run_settings(str(project), {"python": os.path.join(str(project), "no", "python.exe")})
        with pytest.raises(tp.TestProjectError, match="interpreter"):
            tp.RUNS.start(str(project), "testsuites/passing.robot")

    def test_run_settings_reach_the_process(self, project):
        tp.set_run_settings(str(project), {"args": ["--name", "Custom"], "pythonpath": ["libs"],
                                           "env": {"BENCH_ID": "B7"}})
        _write(project, "libs/benchlib.py", "import os\ndef bench_id():\n    return os.environ['BENCH_ID']\n")
        _write(project, "testsuites/uses_lib.robot",
               "*** Settings ***\nLibrary    benchlib\n\n*** Test Cases ***\nId\n"
               "    ${id}=    Bench Id\n    Should Be Equal    ${id}    B7\n")
        st = _wait(project, tp.RUNS.start(str(project), "testsuites/uses_lib.robot")["id"])
        assert st["verdict"] == "pass", st["all_lines"]
        assert st["tests"][0]["suite"] == "Custom"

    def test_one_run_at_a_time_and_graceful_stop(self, project):
        _write(project, "testsuites/slow.robot", SLOW)
        run = tp.RUNS.start(str(project), "testsuites/slow.robot")
        with pytest.raises(tp.TestProjectError, match="already in progress"):
            tp.RUNS.start(str(project), "testsuites/passing.robot")
        deadline = time.time() + 30
        while time.time() < deadline:
            if any("waiting" in l for l in tp.RUNS.status(str(project), run["id"])["lines"]):
                break
            time.sleep(0.2)
        stopped = tp.RUNS.stop(str(project), run["id"])
        assert stopped["run_state"] == "stopping"
        st = _wait(project, run["id"], timeout=40)
        assert st["elapsed_s"] < 40
        assert any("teardown ran" in line for line in st["all_lines"])
        assert st["message"].startswith("Stopped on request")
        assert st["verdict"] == "fail"
        assert (project / "results" / run["id"] / "output.xml").is_file()

    def test_force_stop(self, project):
        _write(project, "testsuites/slow.robot", SLOW)
        run = tp.RUNS.start(str(project), "testsuites/slow.robot")
        time.sleep(1.5)
        tp.RUNS.stop(str(project), run["id"], force=True)
        st = _wait(project, run["id"], timeout=20)
        assert st["run_state"] == "done"
        assert st["verdict"] in ("error", "fail")
        with pytest.raises(tp.TestProjectError, match="not running"):
            tp.RUNS.stop(str(project), run["id"])


class Test_History:

    def test_list_and_stored_status(self, project):
        first = _wait(project, tp.RUNS.start(str(project), "testsuites/passing.robot")["id"])
        second = _wait(project, tp.RUNS.start(str(project), "testsuites/failing.robot")["id"])
        runs = tp.RUNS.list(str(project))["runs"]
        assert [r["id"] for r in runs[:2]] == [second["id"], first["id"]]
        assert runs[0]["verdict"] == "fail" and "tests" not in runs[0]
        # A fresh manager (bridge restart) reads the stored record and console.
        fresh = tp.RunManager().status(str(project), first["id"], 0)
        assert fresh["verdict"] == "pass" and fresh["run_state"] == "done"
        assert any("hello world" in line for line in fresh["lines"])

    def test_stale_running_record_is_closed(self, project):
        run_dir = project / "results" / "20260101-000000_ghost"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps({"id": run_dir.name, "state": "running"}),
                                          encoding="utf-8")
        st = tp.RunManager().status(str(project), run_dir.name, 0)
        assert st["run_state"] == "done" and st["verdict"] == "error"

    def test_artifact_path_is_confined(self, project):
        run = _wait(project, tp.RUNS.start(str(project), "testsuites/passing.robot")["id"])
        assert tp.RUNS.artifact_path(str(project), run["id"], "log.html").endswith("log.html")
        for run_id, name in [(run["id"], "../testproject.json"), ("../x", "log.html"),
                             (run["id"], "missing.html")]:
            with pytest.raises(tp.TestProjectError):
                tp.RUNS.artifact_path(str(project), run_id, name)


@pytest.mark.skipif(not HAS_FLOW, reason="RobotFramework AIO fork with robot.flow not found (MB_FLOW_SRC)")
class Test_Flow:

    def test_flow_gate_timeout_is_unknown(self, project):
        tp.set_run_settings(str(project), {"pythonpath": [FLOW_SRC]})
        _write(project, "testsuites/gate.flow.json", json.dumps(FLOW_UNKNOWN))
        st = _wait(project, tp.RUNS.start(str(project), "testsuites/gate.flow.json")["id"])
        assert "--parser" in st["argv"] and "robot.flow" in st["argv"]
        assert st["verdict"] == "unknown", st["all_lines"]
        assert st["counts"]["unknown"] == 1
        assert st["tests"][0]["name"] == "Gate Times Out"

    def test_flow_without_the_fork_explains_itself(self, project):
        _write(project, "testsuites/gate.flow.json", json.dumps(FLOW_UNKNOWN))
        st = _wait(project, tp.RUNS.start(str(project), "testsuites/gate.flow.json")["id"])
        try:
            import robot.flow  # noqa: F401
            pytest.skip("this interpreter's robot has robot.flow already")
        except ImportError:
            pass
        assert st["verdict"] == "error"
        assert any("robot.flow" in line for line in st["all_lines"])


FLOW_LOOP = {
    "flow": {"name": "Loop With Recovery", "version": 1},
    "nodes": [
        {"id": "start", "kind": "start"},
        {"id": "setup", "kind": "phase", "role": "setup"},
        {"id": "ready", "kind": "gate", "keyword": "Should Be True", "args": ["True"], "timeout": "2s"},
        {"id": "cycle", "kind": "phase", "role": "test", "name": "Cycle"},
        {"id": "loop", "kind": "loop", "max_loops": 3},
        {"id": "step", "kind": "keyword", "keyword": "Log", "args": ["tick"]},
        {"id": "fix", "kind": "keyword", "keyword": "Log", "args": ["recovered"]},
        {"id": "end", "kind": "end"},
    ],
    "edges": [["start", "setup"], ["setup", "ready"], ["ready", "cycle"], ["cycle", "loop"],
              {"from": "loop", "to": "step", "label": "body"},
              {"from": "step", "to": "loop", "label": "next"},
              {"from": "loop", "to": "fix", "label": "on_failure"},
              {"from": "fix", "to": "loop", "label": "continue"},
              {"from": "loop", "to": "end", "label": "done"}],
}


class Test_FileViews:

    def test_flow_files_offer_diagram_and_robot(self, project):
        _write(project, "testsuites/plan.flow.json", json.dumps(FLOW_LOOP))
        files = {f["path"]: f for f in tp.project_tree(str(project))["files"]}
        assert [v["id"] for v in files["testsuites/plan.flow.json"]["views"]] == ["diagram", "robot"]
        assert [v["type"] for v in files["testsuites/plan.flow.json"]["views"]] == ["flow-graph", "code"]
        assert files["testsuites/passing.robot"]["views"] == []
        with pytest.raises(tp.TestProjectError, match="no views"):
            tp.inspect_file(str(project), "testsuites/passing.robot")

    @pytest.mark.skipif(not HAS_FLOW, reason="RobotFramework AIO fork with robot.flow not found (MB_FLOW_SRC)")
    def test_structure_and_robot_text_from_the_fork(self, project):
        tp.set_run_settings(str(project), {"pythonpath": [FLOW_SRC]})
        _write(project, "testsuites/plan.flow.json", json.dumps(FLOW_LOOP))
        res = tp.inspect_file(str(project), "testsuites/plan.flow.json")
        assert res["ok"] is True, res
        flow = res["views"]["diagram"]["flow"]
        assert [s["id"] for s in flow["setup"]["steps"]] == ["ready"]
        loop = flow["tests"][0]["steps"][0]
        assert loop["kind"] == "loop" and loop["max_loops"] == "3"
        assert [s["id"] for s in loop["body"]] == ["step"]
        assert [s["id"] for s in loop["recovery"]] == ["fix"] and loop["then"] == "continue"
        assert flow["teardown"] is None
        text = res["views"]["robot"]["text"]
        assert "WHILE" in text and "Flow Gate" in text and "EXCEPT" in text

    @pytest.mark.skipif(not HAS_FLOW, reason="RobotFramework AIO fork with robot.flow not found (MB_FLOW_SRC)")
    def test_unsaved_text_and_refusals(self, project):
        tp.set_run_settings(str(project), {"pythonpath": [FLOW_SRC]})
        _write(project, "testsuites/plan.flow.json", json.dumps(FLOW_LOOP))
        edited = json.loads(json.dumps(FLOW_LOOP))
        edited["flow"]["name"] = "Edited In The Editor"
        res = tp.inspect_file(str(project), "testsuites/plan.flow.json", json.dumps(edited))
        assert res["views"]["diagram"]["flow"]["name"] == "Edited In The Editor"
        # an extra node nothing leads to: the fork names it
        edited["nodes"].insert(3, {"id": "orphan", "kind": "keyword", "keyword": "Log", "args": ["x"]})
        edited["edges"].append(["orphan", "cycle"])
        res = tp.inspect_file(str(project), "testsuites/plan.flow.json", json.dumps(edited))
        assert res["ok"] is False and res["node"] == "orphan", res
        res = tp.inspect_file(str(project), "testsuites/plan.flow.json", '{\n  "flow": ,\n}')
        assert res["ok"] is False and res["line"] == 2

    def test_without_the_fork_it_says_what_to_do(self, project):
        try:
            import robot.flow  # noqa: F401
            pytest.skip("this interpreter's robot has robot.flow already")
        except ImportError:
            pass
        _write(project, "testsuites/plan.flow.json", json.dumps(FLOW_LOOP))
        res = tp.inspect_file(str(project), "testsuites/plan.flow.json")
        assert res["ok"] is False and res["missing"] is True
        assert "Run settings" in res["error"]


class Test_BridgeEndpoints:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import FastAPIBridge
        bridge = FastAPIBridge(host="localhost", port=1112, allowed_origins="*")
        return TestClient(bridge._build_app() or bridge._app)

    def test_run_poll_and_open_log(self, client, project):
        root = str(project)
        res = client.post("/api/test-project/run", json={"root": root, "path": "testsuites/passing.robot"}).json()
        assert res["status"] == "ok", res
        run_id, since = res["id"], 0
        deadline = time.time() + 90
        while time.time() < deadline:
            st = client.post("/api/test-project/run/status",
                             json={"root": root, "run_id": run_id, "since": since}).json()
            since = st["next"]
            if st["run_state"] == "done":
                break
            time.sleep(0.2)
        assert st["verdict"] == "pass"
        assert st["results_url"].endswith("/%s/" % run_id)
        log = client.get(st["results_url"] + "log.html")
        assert log.status_code == 200 and "<html" in log.text.lower()
        assert client.get(st["results_url"] + "..%2Frun.json").status_code == 404
        runs = client.post("/api/test-project/runs", json={"root": root}).json()
        assert runs["runs"][0]["id"] == run_id and runs["runs"][0]["results_url"]

    def test_settings_and_errors(self, client, project):
        root = str(project)
        got = client.post("/api/test-project/run-settings", json={"root": root}).json()
        assert got["settings"]["pythonpath"] == []
        put = client.post("/api/test-project/run-settings",
                          json={"root": root, "settings": {"pythonpath": ["x"]}}).json()
        assert put["settings"]["pythonpath"] == ["x"]
        bad = client.post("/api/test-project/run-settings",
                          json={"root": root, "settings": {"pythonpath": "x"}}).json()
        assert bad["status"] == "error"
        err = client.post("/api/test-project/run", json={"root": root, "path": "nope.robot"}).json()
        assert err["status"] == "error"
        err = client.post("/api/test-project/run/stop", json={"root": root, "run_id": "20260101-000000_x"}).json()
        assert err["status"] == "error"

    def test_inspect(self, client, project):
        root = str(project)
        _write(project, "testsuites/plan.flow.json", json.dumps(FLOW_LOOP))
        res = client.post("/api/test-project/inspect",
                          json={"root": root, "path": "testsuites/plan.flow.json", "content": "{ nope"}).json()
        assert res["status"] == "ok" and res["ok"] is False and res["line"] == 1
        assert [v["id"] for v in res["available"]] == ["diagram", "robot"]
        err = client.post("/api/test-project/inspect",
                          json={"root": root, "path": "testsuites/passing.robot"}).json()
        assert err["status"] == "error"
