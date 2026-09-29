"""
Tests for the Grid view of Robot Framework suites and resources
(adapters/test_project/robot_grid.py through the Robot Framework AIO
adapter's ``inspect_file``): rows as Robot parses them, and every keyword
resolved from the file's imports the way the run will resolve it.

Runs Robot's parser and Libdoc with the interpreter running the tests.
"""

import json
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, REPO)

from MicroserviceBase.adapters import test_project as tp  # noqa: E402

pytest.importorskip("robot")

LIB = '''\
"""A bench library."""


def read_voltage(channel, *, unit="V"):
    """Reads one channel."""
    return 0.0


def log_all(*values, **options):
    """Logs everything."""
'''

RESOURCE = """\
*** Settings ***
Library    Collections
Resource    inner.resource

*** Keywords ***
Set Signal
    [Documentation]    Write a setpoint.
    ...    Only setpoints accept it.
    [Arguments]    ${name}    ${value}=0
    Log    ${name}=${value}

Temperature Is ${degrees}
    Log    ${degrees}
"""

INNER = """\
*** Keywords ***
Inner Keyword
    [Arguments]    ${a}    @{rest}
    No Operation
"""

SUITE = """\
*** Settings ***
Documentation     Grid sample.
Resource          ../res/bench.resource
Library           ../libs/benchlib.py    WITH NAME    Bench
Library           NoSuchLibraryAnywhere
Resource          ${NOT_KNOWN}/x.resource
Suite Setup       Set Signal    bench.x    1

*** Test Cases ***
Calls
    ${v}=    Read Voltage    ch0    unit=mV    # a comment
    Set Signal    bench.y
    Set Signal    bench.y    2    3
    Wait Until Keyword Succeeds    3s    0.2s    Set Signal    bench.z    4
    Bench.Log All    a    b    level=INFO
    Temperature Is 5
    Inner Keyword    x    y    z
    Dictionary Should Contain Key    ${d}    k
    No Such Keyword    1
    FOR    ${i}    IN RANGE    3
        Log    ${i}
    END
    [Teardown]    Set Signal    bench.x    0

*** Keywords ***
Own Keyword
    [Arguments]    ${first}    ${second}=2
    Own Keyword    only
"""


def _write(root, rel, text):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "grid_tests"
    root.mkdir()
    tp.init_project(str(root), "robotframework-aio")
    _write(root, "libs/benchlib.py", LIB)
    _write(root, "res/bench.resource", RESOURCE)
    _write(root, "res/inner.resource", INNER)
    _write(root, "testsuites/calls.robot", SUITE)
    return root


def _grid(project, rel="testsuites/calls.robot", content=None):
    res = tp.inspect_file(str(project), rel, content)
    assert res["ok"] is True, res
    return res["views"]["grid"]


def _rows(view, section, item=None):
    s = [s for s in view["grid"]["sections"] if s["type"] == section][0]
    if item is None:
        return {r["line"]: r for r in s["rows"]}
    it = [i for i in s["items"] if i["name"] == item][0]
    return {r["line"]: r for r in it["rows"]}


def _cells(row):
    return [(c["v"], c["p"]) for c in row["cells"]]


class Test_View:

    def test_suites_and_resources_offer_the_grid(self, project):
        files = {f["path"]: f for f in tp.project_tree(str(project))["files"]}
        assert files["testsuites/calls.robot"]["views"] == [{"id": "grid", "title": "Grid", "type": "robot-grid"}]
        assert files["res/bench.resource"]["views"][0]["type"] == "robot-grid"
        assert files["libs/benchlib.py"]["views"] == []

    def test_imports_are_resolved_or_explained(self, project):
        view = _grid(project)
        imports = {i["name"]: i for i in view["imports"]}
        assert imports["../res/bench.resource"]["ok"] and imports["../res/bench.resource"]["line"] == 3
        assert imports["../libs/benchlib.py"]["ok"] and imports["../libs/benchlib.py"]["keywords"] == 2
        assert imports["Collections"]["ok"] and imports["Collections"]["via"] == "bench.resource"
        assert imports["inner.resource"]["ok"]
        assert imports["NoSuchLibraryAnywhere"]["ok"] is False and imports["NoSuchLibraryAnywhere"]["error"]
        assert "variables" in imports["${NOT_KNOWN}/x.resource"]["error"]
        assert view["catalog"] > 100          # BuiltIn and Collections included


class Test_Rows:

    def test_keywords_resolve_and_cells_name_their_parameters(self, project):
        rows = _rows(_grid(project), "tests", "Calls")
        read = rows[11]
        assert read["assign"] == ["${v}="] and read["keyword"] == "Read Voltage"
        assert read["kw"] == "bench.readvoltage"                      # the WITH NAME alias
        assert _cells(read) == [("ch0", "channel"), ("unit=mV", "unit")]
        assert read["comment"] == "# a comment"
        assert rows[15]["kw"] == "bench.logall"
        assert _cells(rows[15]) == [("a", "*values"), ("b", "*values"), ("level=INFO", "**options")]
        assert rows[17]["kw"] == "inner.innerkeyword"                 # reached through a resource's import
        assert _cells(rows[17]) == [("x", "a"), ("y", "*rest"), ("z", "*rest")]
        assert rows[18]["kw"] == "collections.dictionaryshouldcontainkey"

    def test_missing_extra_and_unknown(self, project):
        rows = _rows(_grid(project), "tests", "Calls")
        assert rows[12]["missing"] == []                              # value has a default
        assert _cells(rows[13])[-1] == ("3", "(extra)")
        assert rows[19]["kw"] is None and rows[19]["keyword"] == "No Such Keyword"
        own = _rows(_grid(project), "keywords", "Own Keyword")
        assert own[28]["kw"] == "calls.ownkeyword" and own[28]["missing"] == []

    def test_run_keyword_cells_belong_to_the_keyword_they_name(self, project):
        row = _rows(_grid(project), "tests", "Calls")[14]
        assert row["kw"] == "builtin.waituntilkeywordsucceeds"
        assert _cells(row) == [("3s", "retry"), ("0.2s", "retry_interval"), ("Set Signal", "name"),
                               ("bench.z", "name"), ("4", "value")]
        assert row["cells"][2]["kw"] == "bench.setsignal"

    def test_embedded_arguments_blocks_and_fixtures(self, project):
        view = _grid(project)
        rows = _rows(view, "tests", "Calls")
        assert rows[16]["kw"] == "bench.temperatureis${degrees}"
        assert rows[20]["type"] == "FOR" and rows[20]["label"] == "FOR" and rows[20]["depth"] == 0
        assert rows[21]["depth"] == 1 and rows[21]["kw"] == "builtin.log"
        assert rows[22]["type"] == "END"
        assert rows[23]["label"] == "[Teardown]" and rows[23]["kw"] == "bench.setsignal"
        settings = _rows(view, "settings")
        assert settings[7]["label"] == "Suite Setup" and _cells(settings[7]) == [("bench.x", "name"), ("1", "value")]

    def test_only_used_keywords_are_sent_in_full(self, project):
        view = _grid(project)
        kw = view["keywords"]["bench.setsignal"]
        assert kw["owner_type"] == "resource" and kw["shortdoc"].startswith("Write a setpoint.")
        assert [(a["name"], a["required"], a["default"]) for a in kw["args"]] == [("name", True, None), ("value", False, "0")]
        assert "collections.appendtolist" not in view["keywords"]

    def test_unsaved_text_is_what_is_shown(self, project):
        view = _grid(project, content=SUITE.replace("No Such Keyword    1", "Own Keyword    now"))
        row = _rows(view, "tests", "Calls")[19]
        assert row["kw"] == "calls.ownkeyword" and _cells(row) == [("now", "first")]

    def test_a_resource_is_a_grid_too(self, project):
        view = _grid(project, "res/bench.resource")
        rows = _rows(view, "keywords", "Set Signal")
        assert rows[7]["label"] == "[Documentation]"
        assert _cells(rows[7]) == [("Write a setpoint.\nOnly setpoints accept it.", None)]   # one text
        assert rows[9]["label"] == "[Arguments]"
        assert rows[10]["kw"] == "builtin.log"

    def test_values_are_shown_as_written(self, project):
        text = SUITE + "\n*** Variables ***\n${PROTOS}    ${CURDIR}/../proto\n"
        rows = _rows(_grid(project, content=text), "variables")
        assert _cells(rows[31]) == [("${CURDIR}/../proto", None)]      # not the machine's path


EDITABLE = """\
*** Test Cases ***
Steps
    [Documentation]    doc
    Log    a    # keep me
    FOR    ${i}    IN    1    2
        Log    ${i}
    END
    Should Be Equal
    ...    a    b

Empty
    [Tags]    x
"""


class Test_Edit:

    @staticmethod
    def _edit(project, edit, text=EDITABLE, rel="testsuites/edit.robot"):
        return tp.edit_file_view(str(project), rel, "grid", text, edit)

    @pytest.fixture
    def project(self, project):
        _write(project, "testsuites/edit.robot", EDITABLE)
        return project

    def test_set_keeps_everything_else(self, project):
        res = self._edit(project, {"op": "set", "line": 4,
                                   "row": {"assign": ["${x}"], "keyword": "Set Variable", "args": ["a  b", "", " lead"]}})
        assert res["ok"] is True and res["line"] == 4
        lines = res["text"].split("\n")
        assert lines[3] == r"    ${x}=    Set Variable    a \ b    ${EMPTY}    \ lead    # keep me"
        assert lines[:3] == EDITABLE.split("\n")[:3] and lines[4:] == EDITABLE.split("\n")[4:]

    def test_insert_after_a_step_inside_after_a_block_and_first(self, project):
        res = self._edit(project, {"op": "insert", "after": 6, "row": {"keyword": "Log", "args": ["in loop"]}})
        assert res["line"] == 7 and res["text"].split("\n")[6] == "        Log    in loop"
        res = self._edit(project, {"op": "insert", "after": 5, "row": {"keyword": "No Operation"}})
        assert res["line"] == 8 and res["text"].split("\n")[7] == "    No Operation"      # after the FOR block
        res = self._edit(project, {"op": "insert", "item": 11, "row": {"keyword": "Log", "args": ["first"]}})
        assert res["line"] == 13 and res["text"].split("\n")[12] == "    Log    first"   # after [Tags]

    def test_delete_a_step_over_several_lines(self, project):
        res = self._edit(project, {"op": "delete", "line": 8})
        assert "Should Be Equal" not in res["text"] and "    ...    a    b" not in res["text"]
        assert res["text"].count("\n") == EDITABLE.count("\n") - 2

    def test_line_endings_are_kept(self, project):
        crlf = EDITABLE.replace("\n", "\r\n")
        res = self._edit(project, {"op": "insert", "after": 4, "row": {"keyword": "No Operation"}}, text=crlf)
        assert res["ok"] and "\n" not in res["text"].replace("\r\n", "")

    @pytest.mark.parametrize("edit, message", [
        ({"op": "set", "line": 5, "row": {"keyword": "Log"}}, "Only keyword steps"),
        ({"op": "set", "line": 4, "row": {"keyword": ""}}, "Choose a keyword"),
        ({"op": "set", "line": 4, "row": {"keyword": "Log", "assign": ["x"]}}, "not a variable"),
        ({"op": "set", "line": 4, "row": {"keyword": "Log", "args": ["a\nb"]}}, "line breaks"),
        ({"op": "set", "line": 99, "row": {"keyword": "Log"}}, "No step on line 99"),
        ({"op": "swap", "line": 4}, "Unknown edit"),
    ])
    def test_refusals_say_why(self, project, edit, message):
        res = self._edit(project, edit)
        assert res["ok"] is False and message in res["error"], res

    def test_only_the_users_files_are_edited(self, project):
        manifest = json.loads((project / "testproject.json").read_text(encoding="utf-8"))
        manifest["services"]["svc"] = {"files": {"testsuites/edit.robot": {"role": "generated", "sha256": "x"}}}
        (project / "testproject.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(tp.TestProjectError, match="written by an export"):
            self._edit(project, {"op": "delete", "line": 4})
        with pytest.raises(tp.TestProjectError, match="no view"):
            tp.edit_file_view(str(project), "testsuites/edit.robot", "diagram", EDITABLE, {"op": "delete", "line": 4})

    def test_the_catalog_lists_every_keyword(self, project):
        view = _grid(project)
        names = {(k["owner"], k["name"]) for k in view["catalog_list"]}
        assert ("BuiltIn", "Log") in names and ("bench", "Set Signal") in names and ("Bench", "Read Voltage") in names
        assert len(view["catalog_list"]) == view["catalog"]
        assert view["catalog_list"][0]["owner_type"] == "file"            # the file's own first

    def test_bridge_endpoint(self, project):
        from fastapi.testclient import TestClient
        from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import FastAPIBridge
        bridge = FastAPIBridge(host="localhost", port=1112, allowed_origins="*")
        client = TestClient(bridge._build_app() or bridge._app)
        res = client.post("/api/test-project/view-edit", json={
            "root": str(project), "path": "testsuites/edit.robot", "view": "grid", "content": EDITABLE,
            "edit": {"op": "set", "line": 4, "row": {"keyword": "Log", "args": ["b"]}}}).json()
        assert res["status"] == "ok" and res["ok"] is True and "    Log    b    # keep me" in res["text"]
        bad = client.post("/api/test-project/view-edit", json={
            "root": str(project), "path": "../x.robot", "view": "grid", "content": "", "edit": {}}).json()
        assert bad["status"] == "error"


STRUCTURED = """\
*** Settings ***
Library    Collections
Suite Setup    Log    start

*** Variables ***
${LIMIT}    3

*** Test Cases ***
Loops
    [Tags]    smoke
    Log    one
    FOR    ${i}    IN RANGE    ${LIMIT}
        Log    ${i}
    END
    IF    ${LIMIT} > 2
        Log    big
    ELSE
        Log    small
    END
    Log    two

*** Keywords ***
Helper
    [Arguments]    ${x}
    Log    ${x}
"""


class Test_Structure:

    @staticmethod
    def _edit(project, edit, text=STRUCTURED):
        res = tp.edit_file_view(str(project), "testsuites/s.robot", "grid", text, edit)
        assert res["ok"] is True, res
        return res

    @pytest.fixture
    def project(self, project):
        _write(project, "testsuites/s.robot", STRUCTURED)
        return project

    def test_move_steps_and_blocks(self, project):
        res = self._edit(project, {"op": "move", "line": 20, "dir": -1})           # "Log two" above the IF
        lines = res["text"].split("\n")
        assert lines[14] == "    Log    two" and lines[15] == "    IF    ${LIMIT} > 2" and res["line"] == 15
        res = self._edit(project, {"op": "move", "line": 11, "dir": 1})            # "Log one" below the FOR
        lines = res["text"].split("\n")
        assert lines[10] == "    FOR    ${i}    IN RANGE    ${LIMIT}" and lines[13] == "    Log    one" and res["line"] == 14
        res = tp.edit_file_view(str(project), "testsuites/s.robot", "grid", STRUCTURED, {"op": "move", "line": 11, "dir": -1})
        assert res["ok"] is False and "first" in res["error"]                      # [Tags] stays on top

    def test_headers(self, project):
        res = self._edit(project, {"op": "header", "line": 12, "header": {"variables": ["${n}"], "flavor": "IN",
                                                                          "values": ["a", "b c"]}})
        assert "    FOR    ${n}    IN    a    b c" in res["text"]
        res = self._edit(project, {"op": "header", "line": 15, "header": {"condition": "${LIMIT} == 3"}})
        assert "    IF    ${LIMIT} == 3" in res["text"] and "    ELSE\n" in res["text"]
        bad = tp.edit_file_view(str(project), "testsuites/s.robot", "grid", STRUCTURED,
                                {"op": "header", "line": 12, "header": {"variables": ["i"], "values": ["1"]}})
        assert bad["ok"] is False and "loop variable" in bad["error"]

    def test_new_blocks_and_branches(self, project):
        res = self._edit(project, {"op": "block", "after": 20, "block": {"type": "WHILE", "header": {"condition": "True", "limit": "5"}}})
        assert "    WHILE    True    limit=5\n        No Operation\n    END\n" in res["text"] and res["line"] == 21
        res = self._edit(project, {"op": "block", "item": 23, "block": {"type": "TRY"}})
        assert "    TRY\n        No Operation\n    EXCEPT\n        No Operation\n    END\n    Log    ${x}" in res["text"]
        res = self._edit(project, {"op": "branch", "line": 15, "branch": {"type": "ELSE IF", "header": {"condition": "${LIMIT} > 1"}}})
        text = res["text"]
        assert text.index("    ELSE IF    ${LIMIT} > 1") < text.index("    ELSE\n") and res["line"] == 17
        dup = tp.edit_file_view(str(project), "testsuites/s.robot", "grid", STRUCTURED,
                                {"op": "branch", "line": 15, "branch": {"type": "ELSE"}})
        assert dup["ok"] is False and "ELSE already" in dup["error"]

    def test_delete_a_block_or_a_branch(self, project):
        res = self._edit(project, {"op": "delete", "line": 17})                  # the ELSE branch
        assert "ELSE" not in res["text"] and "small" not in res["text"] and "    Log    big\n    END" in res["text"]
        res = self._edit(project, {"op": "delete", "line": 12})                  # the whole FOR
        assert "FOR" not in res["text"] and "Log    ${i}" not in res["text"]
        bad = tp.edit_file_view(str(project), "testsuites/s.robot", "grid", STRUCTURED, {"op": "delete", "line": 14})
        assert bad["ok"] is False and "first row" in bad["error"]                 # an END alone

    def test_fixtures_settings_and_variables(self, project):
        res = self._edit(project, {"op": "set", "line": 3, "row": {"keyword": "Log Many", "args": ["a", "b"]}})
        assert "Suite Setup    Log Many    a    b" in res["text"]
        res = self._edit(project, {"op": "values", "line": 10, "values": ["smoke", "slow"]})
        assert "    [Tags]    smoke    slow" in res["text"]
        res = self._edit(project, {"op": "values", "line": 6, "name": "${MAX}", "values": ["4"]})
        assert "${MAX}    4" in res["text"] and "${LIMIT}    3" not in res["text"]
        res = self._edit(project, {"op": "setting", "section": "settings", "name": "Library", "values": ["String"]})
        assert res["text"].startswith("*** Settings ***\nLibrary    Collections\nSuite Setup    Log    start\nLibrary    String\n\n")
        assert res["line"] == 4
        res = self._edit(project, {"op": "setting", "section": "variables", "name": "@{ITEMS}", "values": ["a", "b"]})
        assert "${LIMIT}    3\n@{ITEMS}    a    b\n\n" in res["text"]
        res = self._edit(project, {"op": "setting", "section": "settings", "name": "Documentation", "values": ["Line 1", "Line 2"]})
        assert re.search(r"\nDocumentation    Line 1\n\.\.\. +Line 2\n", res["text"])    # continued, aligned
        res = self._edit(project, {"op": "delete", "line": 2})
        assert "Library    Collections" not in res["text"]
        bad = tp.edit_file_view(str(project), "testsuites/s.robot", "grid", STRUCTURED,
                                {"op": "setting", "section": "settings", "name": "Frobnicate", "values": ["x"]})
        assert bad["ok"] is False and "not a setting" in bad["error"]

    def test_sections_are_created_when_missing(self, project):
        text = "*** Test Cases ***\nT\n    Log    x\n"
        res = self._edit(project, {"op": "setting", "section": "variables", "name": "${A}", "values": ["1"]}, text=text)
        assert res["text"] == "*** Variables ***\n${A}    1\n\n*** Test Cases ***\nT\n    Log    x\n"
        res = self._edit(project, {"op": "item", "section": "keywords", "name": "My Keyword"}, text=text)
        assert res["text"] == text + "\n*** Keywords ***\nMy Keyword\n    No Operation\n"

    def test_tests_and_keywords(self, project):
        res = self._edit(project, {"op": "item", "section": "tests", "name": "Second Test"})
        assert "    Log    two\n\nSecond Test\n    No Operation\n\n*** Keywords ***" in res["text"] and res["line"] == 22
        res = self._edit(project, {"op": "rename", "line": 9, "name": "Loops Renamed"})
        assert "\nLoops Renamed\n    [Tags]" in res["text"]
        res = self._edit(project, {"op": "delete_item", "line": 23})
        assert "Helper" not in res["text"] and res["text"].endswith("*** Keywords ***\n")
        dup = tp.edit_file_view(str(project), "testsuites/s.robot", "grid", STRUCTURED,
                                {"op": "item", "section": "keywords", "name": "helper"})
        assert dup["ok"] is False and "already" in dup["error"]

    def test_variables_for_completion(self, project):
        _write(project, "res/vars.resource", "*** Variables ***\n${FROM_RESOURCE}    1\n")
        text = STRUCTURED.replace("Library    Collections", "Library    Collections\nResource    ../res/vars.resource")
        view = _grid(project, "testsuites/s.robot", text)
        names = {(v["name"], v["source"]) for v in view["variables"]}
        assert ("${LIMIT}", "s.robot") in names and ("${FROM_RESOURCE}", "vars.resource") in names


THREADED = """\
*** Test Cases ***
Workers
    Log    main
    THREAD    WORKER1    False
        Log    in worker
    END
    Log    main again
"""


class Test_Thread:
    """THREAD blocks: RobotFramework AIO's, offered only where its Robot has them."""

    @pytest.fixture
    def grid_mod(self):
        from robot.parsing.model import blocks
        if not hasattr(blocks, "Thread"):
            pytest.skip("this Robot has no THREAD (RobotFramework AIO)")
        from MicroserviceBase.adapters.test_project import robot_grid
        return robot_grid

    def test_read_add_and_change(self, project, grid_mod):
        _write(project, "testsuites/t.robot", THREADED)
        view = _grid(project, "testsuites/t.robot")
        assert view["features"] == {"thread": True}
        rows = _rows(view, "tests", "Workers")
        assert rows[4]["type"] == "THREAD" and _cells(rows[4]) == [("WORKER1", None), ("False", None)]
        assert rows[5]["depth"] == 1
        res = tp.edit_file_view(str(project), "testsuites/t.robot", "grid", THREADED,
                                {"op": "block", "after": 7, "block": {"type": "THREAD", "header": {"name": "WORKER2", "daemon": "True"}}})
        assert res["ok"] and res["text"].endswith("    Log    main again\n    THREAD    WORKER2    True\n        No Operation\n    END\n")
        res = tp.edit_file_view(str(project), "testsuites/t.robot", "grid", THREADED,
                                {"op": "header", "line": 4, "header": {"name": "PUMP", "daemon": "True"}})
        assert "\n    THREAD    PUMP    True\n        Log    in worker\n" in res["text"]
        bad = tp.edit_file_view(str(project), "testsuites/t.robot", "grid", THREADED,
                                {"op": "header", "line": 4, "header": {"name": "", "daemon": "maybe"}})
        assert bad["ok"] is False and "needs a name" in bad["error"]

    def test_refused_where_robot_has_no_thread(self, grid_mod, monkeypatch):
        monkeypatch.setattr(grid_mod, "has_threads", lambda: False)
        with pytest.raises(grid_mod.EditError, match="RobotFramework AIO"):
            grid_mod.apply_edit(THREADED, {"op": "block", "after": 3, "block": {"type": "THREAD", "header": {"name": "W"}}})


class Test_ItemSettings:

    TEXT = "*** Test Cases ***\nFirst\n    Log    a\n\nSecond\n    [Tags]    x\n    Log    b\n\n*** Keywords ***\nK\n    Log    k\n"

    @pytest.fixture
    def project(self, project):
        _write(project, "testsuites/i.robot", self.TEXT)
        return project

    def _edit(self, project, **edit):
        return tp.edit_file_view(str(project), "testsuites/i.robot", "grid", self.TEXT, dict(op="item_setting", **edit))

    def test_documentation_goes_first(self, project):
        res = self._edit(project, item=2, name="[Documentation]", values=["Checks a.", "Second line."])
        assert res["ok"] and res["line"] == 3
        assert re.search(r"\nFirst\n    \[Documentation\]    Checks a\.\n    \.\.\. +Second line\.\n    Log    a\n", res["text"])
        res = self._edit(project, item=5, name="[Documentation]", values=["Doc"])
        assert "\nSecond\n    [Documentation]    Doc\n    [Tags]    x\n" in res["text"]

    def test_setup_after_settings_teardown_after_steps(self, project):
        res = self._edit(project, item=5, name="[Setup]", values=["Log", "hi"])
        assert "\n    [Tags]    x\n    [Setup]    Log    hi\n    Log    b\n" in res["text"] and res["line"] == 7
        res = self._edit(project, item=2, name="[Teardown]", values=["Log", "bye"])
        assert "\nFirst\n    Log    a\n    [Teardown]    Log    bye\n\nSecond" in res["text"]

    def test_keyword_arguments(self, project):
        res = self._edit(project, item=10, name="[Arguments]", values=["${x}", "${y}=2"])
        assert res["text"].endswith("\nK\n    [Arguments]    ${x}    ${y}=2\n    Log    k\n")

    @pytest.mark.parametrize("edit, message", [
        ({"item": 5, "name": "[Tags]", "values": ["y"]}, "already"),
        ({"item": 10, "name": "[Setup]", "values": ["Log"]}, "not a setting of a keyword"),
        ({"item": 2, "name": "[Documentation]", "values": ["  "]}, "Write the documentation"),
        ({"item": 2, "name": "[Timeout]", "values": ["1s", "2s"]}, "one value"),
        ({"item": 10, "name": "[Arguments]", "values": ["x"]}, "not an argument"),
        ({"item": 99, "name": "[Tags]", "values": ["y"]}, "No test or keyword"),
    ])
    def test_refusals(self, project, edit, message):
        res = self._edit(project, **edit)
        assert res["ok"] is False and message in res["error"], res


class Test_Inside:
    """Steps and blocks go at the end of a block or one of its branches ("into")."""

    TEXT = ("*** Test Cases ***\nT\n    WHILE    ${go}\n        No Operation\n    END\n"
            "    IF    ${a}\n        Log    a\n    ELSE\n        Log    b\n    END\n    Log    after\n")

    @pytest.fixture
    def project(self, project):
        _write(project, "testsuites/in.robot", self.TEXT)
        return project

    def _edit(self, project, edit):
        return tp.edit_file_view(str(project), "testsuites/in.robot", "grid", self.TEXT, edit)

    def test_steps_at_the_end_of_a_block(self, project):
        res = self._edit(project, {"op": "insert", "into": 3, "row": {"keyword": "Log", "args": ["one"]}})
        assert res["ok"] and res["line"] == 5
        assert "    WHILE    ${go}\n        No Operation\n        Log    one\n    END\n" in res["text"]
        again = tp.edit_file_view(str(project), "testsuites/in.robot", "grid", res["text"],
                                  {"op": "insert", "into": 3, "row": {"keyword": "Log", "args": ["two"]}})
        assert "        Log    one\n        Log    two\n    END\n" in again["text"] and again["line"] == 6

    def test_into_one_branch(self, project):
        res = self._edit(project, {"op": "insert", "into": 6, "row": {"keyword": "Log", "args": ["if"]}})
        assert "        Log    a\n        Log    if\n    ELSE\n" in res["text"]
        res = self._edit(project, {"op": "insert", "into": 8, "row": {"keyword": "Log", "args": ["else"]}})
        assert "        Log    b\n        Log    else\n    END\n" in res["text"]

    def test_a_block_inside_a_block(self, project):
        res = self._edit(project, {"op": "block", "into": 3,
                                   "block": {"type": "FOR", "header": {"variables": ["${i}"], "values": ["1"]}}})
        assert "        No Operation\n        FOR    ${i}    IN    1\n            No Operation\n        END\n    END\n" in res["text"]

    def test_not_into_a_step(self, project):
        res = self._edit(project, {"op": "insert", "into": 11, "row": {"keyword": "Log"}})
        assert res["ok"] is False and "is a step" in res["error"]
