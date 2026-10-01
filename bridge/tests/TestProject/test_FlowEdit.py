#  Copyright 2020-2026 Robert Bosch GmbH
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""
flow_edit.py: edits made in a flow's diagram, checked by the fork's validator.

Needs the RobotFramework AIO fork (``MB_FLOW_SRC``) so every result is
validated and can be rendered; skipped otherwise.
"""
import importlib.util
import json
import os
import sys

import pytest

FLOW_SRC = os.environ.get("MB_FLOW_SRC", "")
HAS_FLOW = bool(FLOW_SRC) and os.path.isdir(os.path.join(FLOW_SRC, "robot", "flow"))
if HAS_FLOW and FLOW_SRC not in sys.path:
    sys.path.insert(0, FLOW_SRC)

_here = os.path.join(os.path.dirname(__file__), "..", "..", "MicroserviceBase", "adapters",
                     "test_project", "flow_edit.py")
_spec = importlib.util.spec_from_file_location("flow_edit_under_test", _here)
fe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fe)

pytestmark = pytest.mark.skipif(not HAS_FLOW, reason="RobotFramework AIO fork with robot.flow not found (MB_FLOW_SRC)")

BASE = {
    "flow": {"name": "Edited", "version": 1},
    "nodes": [
        {"id": "start", "kind": "start"},
        {"id": "setup", "kind": "phase", "role": "setup"},
        {"id": "power", "kind": "keyword", "keyword": "Power On"},
        {"id": "test", "kind": "phase", "role": "test", "name": "Cycles"},
        {"id": "loop", "kind": "loop", "max_loops": 2},
        {"id": "read", "kind": "keyword", "keyword": "Read"},
        {"id": "check", "kind": "decision", "condition": "$X"},
        {"id": "ok", "kind": "keyword", "keyword": "Log", "args": ["ok"]},
        {"id": "after", "kind": "keyword", "keyword": "Log", "args": ["after"]},
        {"id": "fix", "kind": "keyword", "keyword": "Recover"},
        {"id": "off", "kind": "keyword", "keyword": "Power Off"},
        {"id": "end", "kind": "end"},
    ],
    "edges": [["start", "setup"], ["setup", "power"], ["power", "test"], ["test", "loop"],
              {"from": "loop", "to": "read", "label": "body"}, ["read", "check"],
              {"from": "check", "to": "ok", "label": "yes"}, {"from": "check", "to": "after", "label": "no"},
              ["ok", "after"], {"from": "after", "to": "loop", "label": "next"},
              {"from": "loop", "to": "fix", "label": "on_failure"}, {"from": "fix", "to": "loop", "label": "continue"},
              {"from": "loop", "to": "off", "label": "done"}, ["off", "end"]],
}
TEXT = json.dumps(BASE)


def robot(text):
    from robot.flow import build_suite, load_flow, render_robot, structure
    return render_robot(build_suite(structure(load_flow(json.loads(text)))))


def lines(text):
    """The test and keyword bodies, as they would run, without indentation noise."""
    return [l.strip() for l in robot(text).splitlines() if l.startswith("    ")]


def edit(change, text=TEXT):
    return fe.apply_edit(text, change)


class Test_Insert:

    def test_before_a_step(self):
        text, node = edit({"op": "insert", "kind": "keyword", "attrs": {"keyword": "Wait Ready"}, "before": "read"})
        assert node == "wait_ready"
        body = lines(text)
        assert body.index("Wait Ready") == body.index("Read") - 1

    def test_after_the_last_step_of_a_loop_body(self):
        text, _ = edit({"op": "insert", "kind": "keyword", "attrs": {"keyword": "Tick"}, "after": "after"})
        body = lines(text)
        assert body.index("Tick") == body.index("Log    after") + 1
        assert "Tick" in body[body.index("Log    after"):body.index("EXCEPT    AS    ${flow_error}")]

    def test_after_a_loop_comes_after_it(self):
        text, _ = edit({"op": "insert", "kind": "sleep", "attrs": {"duration": "2s"}, "after": "loop"})
        body = lines(text)
        assert body.index("Sleep    2s") > body.index("END") and "Power Off" in body

    def test_into_an_empty_branch(self):
        text, _ = edit({"op": "insert", "kind": "keyword", "attrs": {"keyword": "Note"},
                        "branch": {"decision": "check", "label": "no"}})
        body = lines(text)
        assert body[body.index("ELSE") + 1] == "Note"

    def test_a_new_loop_comes_with_a_step_to_replace(self):
        text, node = edit({"op": "insert", "kind": "loop", "attrs": {"id": "retry", "max_loops": 5}, "before": "off"})
        assert node == "retry"
        assert "WHILE    True    limit=5    on_limit=pass" in lines(text)
        assert "No Operation" in lines(text)

    def test_a_new_decision_has_both_branches_empty(self):
        text, node = edit({"op": "insert", "kind": "decision", "attrs": {"condition": "$MODE == 'EMC'"}, "before": "off"})
        body = lines(text)
        assert "IF    $MODE == 'EMC'" in body and body.index("Power Off") > body.index("IF    $MODE == 'EMC'")

    def test_a_new_test_phase(self):
        text, _ = edit({"op": "insert", "kind": "phase", "attrs": {"role": "test", "name": "Second"}, "before": "off"})
        assert "Second" in robot(text).splitlines()


class Test_MoveDeleteUpdateWrap:

    def test_move_a_step(self):
        text, _ = edit({"op": "move", "node": "power", "before": "off"})
        body = lines(text)
        assert body.index("Power On") == body.index("Power Off") - 1
        assert json.loads(text)["nodes"][0]["id"] == "start"

    def test_delete_reconnects(self):
        text, nxt = edit({"op": "delete", "node": "read"})
        assert "Read" not in lines(text) and nxt == "check"

    def test_delete_the_last_body_step_hands_its_next_on(self):
        # 'off' -- the step after the loop -- is not a body step; delete one that is
        # the last of the body after a plain step: 'ok' -> 'after' stays, drop 'ok'.
        text, _ = edit({"op": "delete", "node": "ok"})
        data = json.loads(text)
        assert {"from": "check", "to": "after", "label": "yes"} in data["edges"]
        assert {"from": "after", "to": "loop", "label": "next"} in data["edges"]

    def test_an_empty_branch_cannot_end_a_body(self):
        # Deleting 'after' would leave the decision's empty 'no' branch as the
        # last thing of the loop body, which a flow cannot express.
        with pytest.raises(fe.FlowEditError) as exc:
            edit({"op": "delete", "node": "after"})
        assert "leave a step there" in str(exc.value)

    def test_delete_a_loop_with_everything_in_it(self):
        text, _ = edit({"op": "delete", "node": "loop"})
        ids = {n["id"] for n in json.loads(text)["nodes"]}
        assert not ids & {"loop", "read", "check", "ok", "after", "fix"}
        assert "Power Off" in lines(text)

    def test_delete_the_only_recovery_step_removes_the_recovery(self):
        text, _ = edit({"op": "delete", "node": "fix"})
        assert "EXCEPT    AS    ${flow_error}" not in lines(text)

    def test_update_fields_and_rename(self):
        text, node = edit({"op": "update", "node": "power", "attrs": {"id": "power_on", "args": ["12"]}})
        assert node == "power_on"
        assert "Power On    12" in lines(text)
        assert ["power_on", "test"] in json.loads(text)["edges"]

    def test_wrap_a_step_in_a_try(self):
        text, node = edit({"op": "wrap", "node": "power", "kind": "try"})
        data = json.loads(text)
        assert {"from": node, "to": "power", "label": "body"} in data["edges"]
        assert lines(text)

    def test_writes_one_node_and_one_edge_per_line(self):
        text, _ = edit({"op": "update", "node": "power", "attrs": {"args": ["5"]}})
        assert '    {"id": "power", "kind": "keyword", "keyword": "Power On", "args": ["5"]},' in text.splitlines()
        assert '    ["setup", "power"],' in text.splitlines()


class Test_Refusals:

    @pytest.mark.parametrize("change, words", [
        ({"op": "delete", "node": "start"}, "start node stays"),
        ({"op": "delete", "node": "check"}, "Empty both branches"),
        ({"op": "insert", "kind": "keyword", "before": "start"}, "before the start"),
        ({"op": "insert", "kind": "subroutine", "before": "off"}, "Cannot insert"),
        ({"op": "move", "node": "loop", "before": "off"}, "Only a step"),
        ({"op": "update", "node": "power", "attrs": {"id": "off"}}, "already"),
        ({"op": "jump"}, "Unknown edit"),
    ])
    def test_refused_with_a_reason(self, change, words):
        with pytest.raises(fe.FlowEditError) as exc:
            edit(change)
        assert words in str(exc.value)

    def test_a_body_cannot_become_empty(self):
        one = json.loads(TEXT)
        text, _ = edit({"op": "delete", "node": "read"}, json.dumps(one))
        text, _ = edit({"op": "delete", "node": "ok"}, text)
        text, _ = edit({"op": "delete", "node": "check"}, text)
        with pytest.raises(fe.FlowEditError) as exc:
            edit({"op": "delete", "node": "after"}, text)
        assert "body cannot be empty" in str(exc.value)

    def test_the_validator_has_the_last_word(self):
        with pytest.raises(fe.FlowEditError) as exc:
            edit({"op": "update", "node": "loop", "attrs": {"max_loops": None}})
        assert "unbounded" in str(exc.value)

    def test_broken_json_is_not_edited(self):
        with pytest.raises(fe.FlowEditError) as exc:
            fe.apply_edit("{ nope", {"op": "delete", "node": "x"})
        assert "not valid JSON" in str(exc.value)
