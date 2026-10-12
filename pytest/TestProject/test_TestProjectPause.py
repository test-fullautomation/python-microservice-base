"""
Tests for pausing, resuming and stopping a running flow, step mode, and
continuing a stopped run from its checkpoint (the run manager's control side
and the Robot Framework AIO adapter's use of the fork's flow control).

Real Robot Framework processes with the RobotFramework AIO fork's
``robot.flow`` (pause/resume/checkpoint): the tests run when ``MB_FLOW_SRC``
names the fork's ``src`` folder and it has ``robot/flow/control.py``.
"""

import json
import os
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, REPO)

from MicroserviceBase.adapters import test_project as tp  # noqa: E402

FLOW_SRC = os.environ.get("MB_FLOW_SRC", "")
HAS_CONTROL = bool(FLOW_SRC) and os.path.isfile(os.path.join(FLOW_SRC, "robot", "flow", "control.py"))
pytestmark = pytest.mark.skipif(not HAS_CONTROL, reason="fork with robot.flow.control not found (MB_FLOW_SRC)")

FLOW = "flows/cycle.flow.json"


def _flow(loops=25):
    return json.dumps({
        "flow": {"name": "Cycle", "version": 1},
        "nodes": [{"id": "start", "kind": "start"},
                  {"id": "test", "kind": "phase", "role": "test", "name": "Cycle"},
                  {"id": "loop", "kind": "loop", "max_loops": loops},
                  {"id": "tick", "kind": "keyword", "keyword": "Log", "args": ["tick"]},
                  {"id": "wait", "kind": "keyword", "keyword": "Sleep", "args": ["0.2s"]},
                  {"id": "end", "kind": "end"}],
        "edges": [["start", "test"], ["test", "loop"], {"from": "loop", "to": "tick", "label": "body"},
                  ["tick", "wait"], {"from": "wait", "to": "loop", "label": "next"},
                  {"from": "loop", "to": "end", "label": "done"}]}, indent=2)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "bench_tests"
    root.mkdir()
    tp.init_project(str(root), "robotframework-aio")
    tp.set_run_settings(str(root), {"pythonpath": [FLOW_SRC]})
    path = root / "flows" / "cycle.flow.json"
    path.parent.mkdir(parents=True)
    path.write_text(_flow(), encoding="utf-8")
    return root


def _until(root, run_id, test, timeout=60, what="it"):
    deadline = time.time() + timeout
    st = None
    while time.time() < deadline:
        st = tp.RUNS.status(str(root), run_id, 0)
        if test(st):
            return st
        time.sleep(0.2)
    raise AssertionError("timed out waiting for %s; last status: %s" % (
        what, {k: (st or {}).get(k) for k in ("state", "control", "verdict", "message")}))


def _states(st):
    return {name: p.get("state") for name, p in ((st.get("control") or {}).get("processes") or {}).items()}


def _all(state):
    return lambda st: _states(st) and all(s == state for s in _states(st).values())


def _done(st):
    return st["run_state"] == "done"


class Test_PauseResumeStop:

    def test_pause_hold_resume_stop_then_continue_from_the_checkpoint(self, project):
        run = tp.RUNS.start(str(project), FLOW)
        st = _until(project, run["id"], _all("running"), what="the flow to report running")
        assert st["pausable"] is True

        tp.RUNS.control(str(project), run["id"], "pause")
        paused = _until(project, run["id"], _all("paused"), what="paused")
        assert paused["control"]["command"]["value"] == "pause"
        time.sleep(0.6)                           # the step running when it paused ends first
        seq = (tp.RUNS.status(str(project), run["id"], 0).get("position") or {}).get("seq")
        time.sleep(1.2)                           # then nothing moves while paused
        assert (tp.RUNS.status(str(project), run["id"], 0).get("position") or {}).get("seq") == seq

        tp.RUNS.control(str(project), run["id"], "resume")
        _until(project, run["id"], lambda s: (s.get("position") or {}).get("seq") != seq, what="the flow to move on")

        tp.RUNS.stop(str(project), run["id"])     # a flow: its own stop, with a checkpoint
        st = _until(project, run["id"], _done, what="the end")
        assert st["verdict"] == "unknown", st.get("message")
        assert st.get("restartable") is True
        assert any(f.endswith(".checkpoint.json") for f in os.listdir(project / "results" / run["id"]))

        again = tp.RUNS.restart(str(project), run["id"])
        assert again["id"] != run["id"] and again["continues"] == run["id"]
        assert any(a.startswith("FLOW_CHECKPOINT:") for a in again["argv"])
        st = _until(project, again["id"], _done, timeout=90, what="the continued run")
        assert st["verdict"] == "pass", st.get("message")
        assert not st.get("restartable"), "a finished flow leaves no checkpoint"

    def test_step_mode_goes_one_step_per_resume(self, project):
        run = tp.RUNS.start(str(project), FLOW, step=True)
        assert "FLOW_STEP:yes" in run["argv"]
        first = _until(project, run["id"], _all("paused"), what="the first step's pause")
        time.sleep(1.0)
        held = (tp.RUNS.status(str(project), run["id"], 0).get("position") or {}).get("step", 0)
        tp.RUNS.control(str(project), run["id"], "resume")
        # It pauses before a step starts: one more step entered, then held again.
        nxt = _until(project, run["id"],
                     lambda s: _all("paused")(s) and (s.get("position") or {}).get("step", 0) == held + 1,
                     what="the pause before the next step")
        time.sleep(1.0)
        assert (tp.RUNS.status(str(project), run["id"], 0).get("position") or {}).get("step") == held + 1, "held there"
        tp.RUNS.stop(str(project), run["id"])
        _until(project, run["id"], _done, what="the end")

    def test_a_group_member_alone(self, project):
        tp.set_groups(str(project), [{"id": "pair", "title": "Pair", "members": [
            {"id": "A", "target": FLOW}, {"id": "B", "target": FLOW}]}])
        run = tp.RUNS.start_group(str(project), "pair")
        _until(project, run["id"], lambda s: _states(s) == {"A": "running", "B": "running"},
               what="both members running, named after their ids")
        tp.RUNS.control(str(project), run["id"], "pause", member="A")
        _until(project, run["id"], lambda s: _states(s) == {"A": "paused", "B": "running"}, what="only A paused")
        tp.RUNS.control(str(project), run["id"], "resume", member="A")
        _until(project, run["id"], _all("running"), what="A running again")
        with pytest.raises(tp.TestProjectError, match="No member"):
            tp.RUNS.control(str(project), run["id"], "pause", member="C")
        tp.RUNS.stop(str(project), run["id"])
        st = _until(project, run["id"], _done, timeout=90, what="the end")
        assert all(m["verdict"] == "unknown" for m in st["members"]), [m["verdict"] for m in st["members"]]

    def test_a_suite_is_not_paused(self, project):
        (project / "testsuites" / "s.robot").write_text("*** Test Cases ***\nT\n    Sleep    1s\n", encoding="utf-8")
        run = tp.RUNS.start(str(project), "testsuites/s.robot")
        with pytest.raises(tp.TestProjectError, match="cannot pause"):
            tp.RUNS.control(str(project), run["id"], "pause")
        with pytest.raises(tp.TestProjectError, match="no step mode"):
            tp.RUNS.start(str(project), "testsuites/s.robot", step=True)
        _until(project, run["id"], _done)
