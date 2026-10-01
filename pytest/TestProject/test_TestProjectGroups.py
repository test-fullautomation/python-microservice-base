"""
Tests for run groups: processes of a test project started together that
meet through the bench (adapters/test_project engine + runs, the Robot
Framework AIO adapter's group view, and the bridge endpoints).

Group runs start real Robot Framework processes. Two members "meet" through
a file in the run's own folder (``${RUN_DIR}`` in the group's env): one
creates it, the other waits for it -- the same shape as two flows meeting
at a gate. The flow-group view needs the RobotFramework AIO fork's
``robot.flow`` (``MB_FLOW_SRC``) and skips otherwise.
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

ANNOUNCE = """\
*** Settings ***
Library    OperatingSystem

*** Test Cases ***
Announce
    Log To Console    ${WHO} is here
    Create File    %{MEET}    ${WHO}
"""

MEET = """\
*** Settings ***
Library    OperatingSystem

*** Test Cases ***
Meet
    Wait Until Created    %{MEET}    timeout=30s
    ${peer}=    Get File    %{MEET}
    Log To Console    ${WHO} met ${peer}
"""

FAILS = """\
*** Test Cases ***
Breaks
    Fail    no peer
"""

SLOW = """\
*** Settings ***
Suite Teardown    Log To Console    ${WHO} teardown ran

*** Test Cases ***
Waits
    Log To Console    ${WHO} waiting
    Sleep    60s
"""

RENDEZVOUS = {
    "flow": {"name": "Rendezvous", "version": 1},
    "variables": {"BLADE": "IVI", "PEER": "ADAS"},
    "nodes": [
        {"id": "start", "kind": "start"},
        {"id": "setup", "kind": "phase", "role": "setup"},
        {"id": "announce", "kind": "keyword", "keyword": "Set Signal", "args": ["bench.${BLADE}.ready", 1]},
        {"id": "test", "kind": "phase", "role": "test", "name": "Meet"},
        {"id": "meet", "kind": "gate", "keyword": "Signal Should Be",
         "args": ["bench.${PEER}.ready", "==", 1], "timeout": "5s"},
        {"id": "end", "kind": "end"},
    ],
    "edges": [["start", "setup"], ["setup", "announce"], ["announce", "test"],
              ["test", "meet"], ["meet", "end"]],
}


def _write(root, rel, text):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _wait(root, run_id, timeout=90):
    deadline = time.time() + timeout
    lines, member_lines, since = [], [], 0
    while time.time() < deadline:
        st = tp.RUNS.status(str(root), run_id, since)
        lines += st["lines"]
        member_lines += st.get("member_lines", [])
        since = st["next"]
        if st["run_state"] == "done":
            st["all_lines"], st["all_member_lines"] = lines, member_lines
            return st
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


def _group(gid="pair", a="testsuites/announce.robot", b="testsuites/meet.robot", **extra):
    group = {"id": gid, "title": "A meets B",
             "env": {"MEET": "${RUN_DIR}/meet.txt"},
             "members": [{"id": "A", "target": a, "variables": {"WHO": "alpha"}},
                         {"id": "B", "target": b, "variables": {"WHO": "beta"}}]}
    group.update(extra)
    return group


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "bench_tests"
    root.mkdir()
    tp.init_project(str(root), "robotframework-aio")
    _write(root, "testsuites/announce.robot", ANNOUNCE)
    _write(root, "testsuites/meet.robot", MEET)
    _write(root, "testsuites/fails.robot", FAILS)
    _write(root, "testsuites/slow.robot", SLOW)
    return root


class Test_Definition:

    def test_round_trip_and_tree(self, project):
        out = tp.set_groups(str(project), [_group()])
        assert out["groups"][0]["runnable"] is True
        assert out["groups"][0]["views"] == []          # .robot members: no flow view
        manifest = json.loads((project / "testproject.json").read_text(encoding="utf-8"))
        assert manifest["groups"][0]["members"][1] == {"id": "B", "target": "testsuites/meet.robot",
                                                       "variables": {"WHO": "beta"}}
        tree = tp.project_tree(str(project))
        assert [g["id"] for g in tree["groups"]] == ["pair"]
        assert tp.get_groups(str(project))["groups"][0]["title"] == "A meets B"
        tp.set_groups(str(project), [])
        manifest = json.loads((project / "testproject.json").read_text(encoding="utf-8"))
        assert "groups" not in manifest

    def test_flow_members_offer_the_group_diagram(self, project):
        _write(project, "pairs/rendezvous.flow.json", json.dumps(RENDEZVOUS))
        out = tp.set_groups(str(project), [_group(members=[
            {"id": "IVI", "target": "pairs/rendezvous.flow.json", "variables": {"BLADE": "IVI", "PEER": "ADAS"}},
            {"id": "ADAS", "target": "pairs/rendezvous.flow.json", "variables": {"BLADE": "ADAS", "PEER": "IVI"}}])])
        assert out["groups"][0]["views"] == [{"id": "sync", "title": "Diagram", "type": "flow-group"}]

    @pytest.mark.parametrize("change, message", [
        ({"members": [{"id": "A", "target": "testsuites/announce.robot"}]}, "2 to 8 members"),
        ({"id": "bad id"}, "must be letters"),
        ({"members": [{"id": "A", "target": "testsuites/announce.robot"},
                      {"id": "A", "target": "testsuites/meet.robot"}]}, "two members"),
        ({"members": [{"id": "A", "target": "testsuites/announce.robot"},
                      {"id": "B", "target": "testsuites/config/robot_config.jsonp"}]}, "cannot run"),
        ({"members": [{"id": "A", "target": "testsuites/announce.robot"},
                      {"id": "B", "target": "../outside.robot"}]}, "escapes"),
        ({"members": [{"id": "A", "target": "testsuites/announce.robot", "variables": {"A B": "1"}},
                      {"id": "B", "target": "testsuites/meet.robot"}]}, "invalid variable name"),
        ({"env": {"X": 1}}, "'env'"),
        ({"shell": "x"}, "unknown keys"),
    ])
    def test_invalid_groups_are_refused(self, project, change, message):
        with pytest.raises(tp.TestProjectError, match=message):
            tp.set_groups(str(project), [_group(**change)])

    def test_duplicate_group_ids(self, project):
        with pytest.raises(tp.TestProjectError, match="Two groups"):
            tp.set_groups(str(project), [_group(), _group()])


class Test_GroupRun:

    def test_members_meet_and_pass(self, project):
        tp.set_groups(str(project), [_group()])
        run = tp.RUNS.start_group(str(project), "pair")
        assert run["group"] == "pair" and [m["id"] for m in run["members"]] == ["A", "B"]
        st = _wait(project, run["id"])
        assert st["verdict"] == "pass", st["all_lines"]
        assert st["counts"]["pass"] == 2
        assert {t["member"] for t in st["tests"]} == {"A", "B"}
        assert [m["verdict"] for m in st["members"]] == ["pass", "pass"]
        # Console: tagged lines, and the same lines routed to their member.
        # (Robot prints Log To Console output on the test's own line.)
        assert any(line.startswith("[A] ") and "alpha is here" in line for line in st["all_lines"])
        assert any(tag == 1 and "beta met alpha" in line for tag, line in st["all_member_lines"])
        assert not any(tag == 0 and "beta" in line for tag, line in st["all_member_lines"])
        # One folder per member, each with the runner's own output.
        out_dir = project / "results" / run["id"]
        for member in ("A", "B"):
            for name in ("log.html", "output.xml", "console.log"):
                assert (out_dir / member / name).is_file(), (member, name)
        assert (out_dir / "meet.txt").is_file()             # ${RUN_DIR} was the run folder
        assert (out_dir / "console.log").is_file() and (out_dir / "run.json").is_file()
        assert tp.RUNS.artifact_path(str(project), run["id"], "log.html", "B").endswith("log.html")
        with pytest.raises(tp.TestProjectError):
            tp.RUNS.artifact_path(str(project), run["id"], "log.html", "..")

    def test_a_failing_member_fails_the_run(self, project):
        tp.set_groups(str(project), [_group(b="testsuites/fails.robot")])
        st = _wait(project, tp.RUNS.start_group(str(project), "pair")["id"])
        assert [m["verdict"] for m in st["members"]] == ["pass", "fail"]
        assert st["verdict"] == "fail"
        broken = [t for t in st["tests"] if t["member"] == "B"][0]
        assert broken["status"] == "fail" and broken["message"] == "no peer"

    def test_history_and_stored_status(self, project):
        tp.set_groups(str(project), [_group()])
        run = _wait(project, tp.RUNS.start_group(str(project), "pair")["id"])
        listed = tp.RUNS.list(str(project))["runs"][0]
        assert listed["id"] == run["id"] and listed["group"] == "pair"
        assert "tests" not in listed and all("tests" not in m for m in listed["members"])
        fresh = tp.RunManager().status(str(project), run["id"], 0)
        assert fresh["verdict"] == "pass" and len(fresh["members"]) == 2
        assert any(tag == 1 and "beta met alpha" in line for tag, line in fresh["member_lines"])

    def test_members_finishing_together_leave_a_readable_record(self, project):
        # Both members end within milliseconds of each other; their threads
        # used to write run.json at the same time and leave it corrupt.
        _write(project, "testsuites/quick.robot", "*** Test Cases ***\nQuick\n    No Operation\n")
        tp.set_groups(str(project), [_group(a="testsuites/quick.robot", b="testsuites/quick.robot", env={})])
        for _ in range(3):
            run = _wait(project, tp.RUNS.start_group(str(project), "pair")["id"])
            record = json.loads((project / "results" / run["id"] / "run.json").read_text(encoding="utf-8"))
            assert record["verdict"] == "pass" and len(record["members"]) == 2
        assert len(tp.RUNS.list(str(project))["runs"]) == 3

    def test_an_unreadable_record_does_not_hide_the_history(self, project):
        tp.set_groups(str(project), [_group()])
        good = _wait(project, tp.RUNS.start_group(str(project), "pair")["id"])
        bad = project / "results" / "20260101-000000_pair"
        bad.mkdir()
        (bad / "run.json").write_text("{} trailing", encoding="utf-8")
        runs = {r["id"]: r for r in tp.RUNS.list(str(project))["runs"]}
        assert runs[good["id"]]["verdict"] == "pass"
        assert runs[bad.name]["verdict"] == "error" and "cannot be read" in runs[bad.name]["message"]

    def test_one_run_at_a_time_and_stop_stops_every_member(self, project):
        tp.set_groups(str(project), [_group(a="testsuites/slow.robot", b="testsuites/slow.robot")])
        run = tp.RUNS.start_group(str(project), "pair")
        with pytest.raises(tp.TestProjectError, match="already in progress"):
            tp.RUNS.start(str(project), "testsuites/announce.robot")
        deadline, seen = time.time() + 30, set()
        while time.time() < deadline and len(seen) < 2:
            for tag, line in tp.RUNS.status(str(project), run["id"]).get("member_lines", []):
                if "waiting" in line:
                    seen.add(tag)
            time.sleep(0.2)
        assert tp.RUNS.stop(str(project), run["id"])["run_state"] == "stopping"
        st = _wait(project, run["id"], timeout=45)
        assert st["elapsed_s"] < 45
        assert any("alpha teardown ran" in l for l in st["all_lines"])
        assert any("beta teardown ran" in l for l in st["all_lines"])
        assert all(m["message"].startswith("Stopped on request") for m in st["members"])

    def test_unknown_group(self, project):
        with pytest.raises(tp.TestProjectError, match="No run group"):
            tp.RUNS.start_group(str(project), "nope")


class Test_SyncLinks:

    @staticmethod
    def _members():
        flow = {"setup": {"steps": [{"id": "announce", "kind": "keyword", "keyword": "Set Signal",
                                     "args": ["bench.${blade}.ready", "1"]}]},
                "tests": [{"steps": [
                    {"id": "meet", "kind": "gate", "keyword": "Signal Should Be",
                     "args": ["bench.${PEER}.ready", "==", "1.0"]},
                    {"id": "loop", "kind": "loop", "body": [
                        {"id": "again", "kind": "keyword", "keyword": "set_signal",
                         "args": ["bench.${BLADE}.ready", "2"]}]}]}],
                "teardown": None}
        return [{"id": "IVI", "flow": flow, "values": {"BLADE": "IVI", "PEER": "ADAS"}},
                {"id": "ADAS", "flow": flow, "values": {"BLADE": "ADAS", "PEER": "IVI"}}]

    def test_each_announcement_reaches_the_peer_gate(self):
        links = tp.sync_links(self._members())
        assert links == [
            {"from": {"member": "IVI", "node": "announce"}, "to": {"member": "ADAS", "node": "meet"},
             "label": "bench.IVI.ready = 1"},
            {"from": {"member": "ADAS", "node": "announce"}, "to": {"member": "IVI", "node": "meet"},
             "label": "bench.ADAS.ready = 1"},
        ]     # value 2 (in the loop body) matches no gate; 1 == 1.0

    def test_no_link_within_one_member_or_without_a_gate(self):
        members = self._members()[:1]
        members[0]["values"]["PEER"] = "IVI"
        assert tp.sync_links(members) == []


@pytest.mark.skipif(not HAS_FLOW, reason="RobotFramework AIO fork with robot.flow not found (MB_FLOW_SRC)")
class Test_GroupView:

    def test_members_flows_and_links_from_the_fork(self, project):
        tp.set_run_settings(str(project), {"pythonpath": [FLOW_SRC]})
        _write(project, "pairs/rendezvous.flow.json", json.dumps(RENDEZVOUS))
        tp.set_groups(str(project), [{"id": "meet", "members": [
            {"id": "IVI", "target": "pairs/rendezvous.flow.json", "variables": {"BLADE": "IVI", "PEER": "ADAS"}},
            {"id": "ADAS", "target": "pairs/rendezvous.flow.json", "variables": {"BLADE": "ADAS", "PEER": "IVI"}}]}])
        res = tp.inspect_group(str(project), "meet")
        assert res["ok"] is True, res
        view = res["views"]["sync"]
        assert [m["id"] for m in view["members"]] == ["IVI", "ADAS"]
        assert view["members"][0]["flow"]["variables"] == {"BLADE": "IVI", "PEER": "ADAS"}
        assert {(l["from"]["member"], l["to"]["member"]) for l in view["links"]} == {("IVI", "ADAS"), ("ADAS", "IVI")}

    def test_a_refused_member_is_named(self, project):
        tp.set_run_settings(str(project), {"pythonpath": [FLOW_SRC]})
        _write(project, "pairs/good.flow.json", json.dumps(RENDEZVOUS))
        broken = json.loads(json.dumps(RENDEZVOUS))
        broken["edges"] = broken["edges"][:-1]           # "end" is unreachable
        _write(project, "pairs/broken.flow.json", json.dumps(broken))
        tp.set_groups(str(project), [{"id": "meet", "members": [
            {"id": "IVI", "target": "pairs/good.flow.json"},
            {"id": "ADAS", "target": "pairs/broken.flow.json"}]}])
        res = tp.inspect_group(str(project), "meet")
        assert res["ok"] is False and res["member"] == "ADAS", res
        assert res["error"].startswith("ADAS (pairs/broken.flow.json)")


# Two flows that meet through the fork's robot.flow.signals: the driver goes,
# the checker waits for it and acknowledges, the driver waits for that.
def _signal_flow(name, steps):
    nodes = [{"id": "start", "kind": "start"}, {"id": "t", "kind": "phase", "role": "test", "name": name}]
    nodes += steps + [{"id": "end", "kind": "end"}]
    ids = [n["id"] for n in nodes]
    return {"flow": {"name": name}, "imports": {"libraries": ["robot.flow.signals"]},
            "nodes": nodes, "edges": [[a, b] for a, b in zip(ids, ids[1:])]}


SIGNAL_DRIVER = _signal_flow("Drive", [
    {"id": "go", "kind": "keyword", "keyword": "Set Signal", "args": ["go", "1"]},
    {"id": "acked", "kind": "gate", "keyword": "Signal Should Be", "args": ["ack", "==", "1"],
     "timeout": "20s", "interval": "0.1s", "on_timeout": "fail"}])
SIGNAL_CHECKER = _signal_flow("Check", [
    {"id": "went", "kind": "gate", "keyword": "Signal Should Be", "args": ["go", "==", "1"],
     "timeout": "20s", "interval": "0.1s", "on_timeout": "fail"},
    {"id": "ack", "kind": "keyword", "keyword": "Set Signal", "args": ["ack", "1"]}])


@pytest.mark.skipif(not HAS_FLOW, reason="RobotFramework AIO fork with robot.flow not found (MB_FLOW_SRC)")
class Test_RunSignals:
    """Each run has its own robot.flow.signals store: the members of a group
    run share it, and the next run starts with a new one."""

    def _setup(self, project, env=None):
        tp.set_run_settings(str(project), {"pythonpath": [FLOW_SRC], "env": env or {}})
        _write(project, "pairs/drive.flow.json", json.dumps(SIGNAL_DRIVER))
        _write(project, "pairs/check.flow.json", json.dumps(SIGNAL_CHECKER))
        tp.set_groups(str(project), [{"id": "hand", "members": [
            {"id": "DRIVER", "target": "pairs/drive.flow.json"},
            {"id": "CHECKER", "target": "pairs/check.flow.json"}]}])

    def test_members_meet_in_the_runs_store(self, project):
        self._setup(project)
        first = _wait(project, tp.RUNS.start_group(str(project), "hand")["id"])
        assert first["verdict"] == "pass", first["all_lines"]
        store = project / "results" / first["id"] / "signals.json"
        data = json.loads(store.read_text(encoding="utf-8"))
        assert {k: v["value"] for k, v in data.items()} == {"go": 1, "ack": 1}
        # A new run: a new store, nothing left over from the first.
        second = _wait(project, tp.RUNS.start_group(str(project), "hand")["id"])
        assert second["verdict"] == "pass", second["all_lines"]
        assert (project / "results" / second["id"] / "signals.json").is_file()
        assert second["id"] != first["id"]

    def test_run_settings_choose_another_store(self, project, tmp_path):
        shared = tmp_path / "bench" / "signals.json"
        self._setup(project, env={"ROBOT_FLOW_SIGNALS": str(shared)})
        st = _wait(project, tp.RUNS.start_group(str(project), "hand")["id"])
        assert st["verdict"] == "pass", st["all_lines"]
        assert shared.is_file()
        assert not (project / "results" / st["id"] / "signals.json").exists()

    def test_a_single_flow_run_has_its_own_store(self, project):
        self._setup(project)
        _write(project, "pairs/solo.flow.json", json.dumps(_signal_flow("Solo", [
            {"id": "set", "kind": "keyword", "keyword": "Set Signal", "args": ["state", "ready"]},
            {"id": "see", "kind": "gate", "keyword": "Signal Should Be", "args": ["state", "==", "ready"],
             "timeout": "2s"}])))
        st = _wait(project, tp.RUNS.start(str(project), "pairs/solo.flow.json")["id"])
        assert st["verdict"] == "pass", st["all_lines"]
        data = json.loads((project / "results" / st["id"] / "signals.json").read_text(encoding="utf-8"))
        assert data["state"]["value"] == "ready"


class Test_BridgeEndpoints:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import FastAPIBridge
        bridge = FastAPIBridge(host="localhost", port=1112, allowed_origins="*")
        return TestClient(bridge._build_app() or bridge._app)

    def test_groups_run_and_member_files(self, client, project):
        root = str(project)
        put = client.post("/api/test-project/groups", json={"root": root, "groups": [_group()]}).json()
        assert put["status"] == "ok" and put["groups"][0]["id"] == "pair"
        got = client.post("/api/test-project/groups", json={"root": root}).json()
        assert got["groups"][0]["members"][0]["id"] == "A"
        bad = client.post("/api/test-project/groups", json={"root": root, "groups": [{"id": "x"}]}).json()
        assert bad["status"] == "error"
        res = client.post("/api/test-project/run", json={"root": root, "group": "pair"}).json()
        assert res["status"] == "ok" and res["group"] == "pair", res
        deadline, since = time.time() + 90, 0
        while time.time() < deadline:
            st = client.post("/api/test-project/run/status",
                             json={"root": root, "run_id": res["id"], "since": since}).json()
            since = st["next"]
            if st["run_state"] == "done":
                break
            time.sleep(0.2)
        assert st["verdict"] == "pass"
        log = client.get(st["results_url"] + "B/log.html")
        assert log.status_code == 200 and "<html" in log.text.lower()
        assert client.get(st["results_url"] + "..%2FA/log.html").status_code == 404
        err = client.post("/api/test-project/group/inspect", json={"root": root, "group": "pair"}).json()
        assert err["status"] == "error"                   # .robot members: nothing to draw
