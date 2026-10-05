"""
Tests for a second test runner (adapters/test_project/temporal.py): that the
engine, the run manager and the bridge take everything runner-specific from
the runner -- file kinds, detection, syntax checks, new files, run command,
results -- and that runners from other packages are found as entry points.

The live run starts a real Temporal dev server, a worker and a gRPC
service, and runs the generated starter test plus a workflow that calls the
service. It needs ``temporalio`` in the interpreter running the tests and
the ``temporal`` CLI in ``TEMPORAL_CLI``; it skips otherwise.
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent import futures

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, REPO)

from MicroserviceBase.adapters import test_project as tp  # noqa: E402
from MicroserviceBase.adapters.test_project import engine  # noqa: E402
from MicroserviceBase.ports.test_project import RunOptions, RunSettings  # noqa: E402

HELLO_PROTO = os.path.join(REPO, "examples", "hello_service", "proto", "hello.proto")
HELLO_FQN = "hello.v1.HelloService"
CONSUL = "http://127.0.0.1:8501"
RUNNER = "temporal-python"

ACTIVITIES = "activities/hello/hello_service.py"
PACKAGE = "activities/hello/__init__.py"
WORKFLOW = "workflows/hello_smoke.py"
TEST = "tests/hello_smoke_test.py"


def _read(root, rel):
    with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def _write(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _export(root, **kwargs):
    files, warnings = tp.collect_proto_set(HELLO_PROTO)
    return tp.export_service(
        str(root), "hello", consul_addr=CONSUL, grpc_services=[HELLO_FQN],
        proto_files=files, source={"kind": "proto", "path": HELLO_PROTO},
        warnings=warnings, **kwargs)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "workflow_tests"
    root.mkdir()
    tp.init_project(str(root), RUNNER, consul_addr=CONSUL)
    _export(root, apply=True)
    return root


class Test_Registry:

    def test_both_runners_are_offered_with_their_structure(self, tmp_path):
        d = tp.describe(str(tmp_path))
        runners = {r["id"]: r for r in d["runners"]}
        assert {"robotframework-aio", RUNNER} <= set(runners)
        assert d["default_runner"] == "robotframework-aio"
        assert any(row[0] == "conftest.py" for row in runners[RUNNER]["structure"])
        assert runners[RUNNER]["description"]

    def test_detection_is_per_runner(self, tmp_path):
        _write(tmp_path, "flows/run.py", "from temporalio import workflow\n")
        _write(tmp_path, "suites/a.robot", "*** Test Cases ***\n")
        d = tp.describe(str(tmp_path))
        assert d["detected"][RUNNER]["count"] == 1
        assert "temporalio" in d["detected"][RUNNER]["summary"]
        assert d["detected"]["robotframework-aio"]["count"] == 1

    def test_runner_from_an_entry_point(self, monkeypatch):
        """A runner another package declares is registered on first use; a
        broken one is noted, not fatal, and none replaces a built-in."""
        from importlib import metadata

        class Fake(tp.TestProjectRunner):
            runner_id = "fake-runner"
            display_name = "Fake"

            def default_layout(self):
                return {"proto": "proto"}

            def init_files(self, layout, project_name, consul_addr):
                return {}

            def service_files(self, layout, export, *, create_starter=True):
                return []

            def run_hint(self, layout, export):
                return ""

        class EP:
            group = tp.RUNNER_ENTRY_POINTS

            def __init__(self, name, obj):
                self.name, self._obj = name, obj

            def load(self):
                if isinstance(self._obj, Exception):
                    raise self._obj
                return self._obj

        class Found(list):
            def select(self, group):
                return [ep for ep in self if ep.group == group]

        eps = Found([EP("fake", Fake), EP("broken", ImportError("no such module")),
                     EP("shadow", type("Shadow", (Fake,), {"runner_id": "robotframework-aio"}))])
        monkeypatch.setattr(metadata, "entry_points", lambda: eps)
        monkeypatch.setattr(engine, "_PLUGINS_LOADED", False)
        monkeypatch.setattr(engine, "_RUNNERS", dict(engine._RUNNERS))
        monkeypatch.setattr(engine, "PLUGIN_ERRORS", {})
        ids = [r["id"] for r in tp.available_runners()]
        assert "fake-runner" in ids
        assert "broken" in engine.PLUGIN_ERRORS
        assert type(tp.get_runner("robotframework-aio")).__name__ == "RobotAioRunner"


class Test_Project:

    def test_init_and_export_write_the_runners_files(self, project):
        for rel in ("conftest.py", "pytest.ini", "requirements.txt", ACTIVITIES, PACKAGE,
                    WORKFLOW, TEST, "proto/hello/hello.proto"):
            assert os.path.isfile(os.path.join(project, *rel.split("/"))), rel
        mod = _read(project, ACTIVITIES)
        assert '@activity.defn(name="HelloService.Greet")' in mod
        assert "def greet(" in mod and "def tick(" in mod and "def reachable(" in mod
        assert "CONSUL_ADDR" in mod and "HELLO_ADDR" in mod
        assert "hello_service.greet," in _read(project, PACKAGE)
        # every generated and starter Python file compiles
        for rel in (ACTIVITIES, PACKAGE, WORKFLOW, TEST, "conftest.py"):
            compile(_read(project, rel), rel, "exec")

    def test_reexport_on_another_day_is_unchanged(self, project):
        path = os.path.join(project, *ACTIVITIES.split("/"))
        text = _read(project, ACTIVITIES).replace("Generated: ", "Generated: 1999-01-01 was ")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        plan = _export(project)
        status = {f["path"]: f["status"] for f in plan["files"]}
        assert status[ACTIVITIES] == "unchanged"

    def test_tree_kinds_groups_and_run_hints(self, project):
        tree = tp.project_tree(str(project))
        kinds = {f["path"]: f["kind"] for f in tree["files"]}
        assert kinds[TEST] == "suite" and kinds[WORKFLOW] == "flow"
        assert kinds[ACTIVITIES] == "resource" and kinds["conftest.py"] == "config"
        assert kinds["proto/hello/hello.proto"] == "proto"
        groups = {k["kind"]: k for k in tree["kinds"]}
        assert groups["suite"]["title"] == "Tests" and groups["flow"]["title"] == "Workflows"
        assert groups["resource"]["title"] == "Activities"
        assert tree["can_run"] and tree["can_new_suite"] and tree["can_new_flow"]
        test = next(f for f in tree["files"] if f["path"] == TEST)
        assert test["runnable"] and test["run_hint"] == f"python -m pytest {TEST}"
        assert not next(f for f in tree["files"] if f["path"] == WORKFLOW)["runnable"]

    def test_syntax_check_is_the_runners(self, project):
        problems = tp.check_syntax(TEST, "def broken(:\n    pass\n", str(project))
        assert problems and problems[0]["line"] == 1
        assert tp.check_syntax(TEST, "x = 1\n", str(project)) == []
        # Robot text is not this project's business
        assert tp.check_syntax("a.robot", "*** Bogus ***\n", str(project)) == []

    def test_new_test_and_workflow(self, project):
        res = tp.create_suite(str(project), "greeting", service="hello")
        assert res["path"] == "tests/greeting_test.py" and res["problems"] == []
        assert "from activities.hello import ACTIVITIES" in _read(project, res["path"])
        res = tp.create_flow(str(project), "climate_debounce", resources=[ACTIVITIES])
        assert res["path"] == "workflows/climate_debounce.py" and res["problems"] == []
        text = _read(project, res["path"])
        assert "class ClimateDebounce:" in text and "from activities.hello import hello_service" in text
        with pytest.raises(tp.TestProjectError, match=r"must end in _test\.py, \.py"):
            tp.write_project_file(str(project), "tests/x.robot", "x", create=True)


class Test_RunSide:

    def test_run_plan(self, project):
        runner = tp.get_runner(RUNNER)
        layout = runner.default_layout()
        out = str(project / "results" / "x")
        os.makedirs(out)
        plan = runner.run_plan(str(project), layout, TEST,
                               RunSettings(env={"TEMPORAL_ADDRESS": "srv:7233"}),
                               RunOptions(variables={"LEVEL": "3"}, dryrun=True), out)
        assert plan.argv[1:3] == ["-m", "pytest"] and "--collect-only" in plan.argv
        assert any(a.startswith("--junitxml=") for a in plan.argv)
        assert plan.env["LEVEL"] == "3" and plan.env["TEMPORAL_ADDRESS"] == "srv:7233"
        assert plan.env["PYTHONPATH"].split(os.pathsep)[0] == str(project)
        assert plan.stop_file and plan.env["MM_RUN_STOP_FILE"] == plan.stop_file
        with pytest.raises(tp.TestProjectError, match="not a test file"):
            runner.run_plan(str(project), layout, WORKFLOW, RunSettings(), RunOptions(), out)

    def test_read_results_from_junit(self, tmp_path):
        _write(tmp_path, "junit.xml", """<?xml version="1.0"?>
<testsuites><testsuite name="pytest" tests="3">
  <testcase classname="tests.a_test" name="test_ok" time="0.5"/>
  <testcase classname="tests.a_test" name="test_bad" time="1.25">
    <failure message="AssertionError: assert 1 == 2">trace</failure></testcase>
  <testcase classname="tests.a_test" name="test_later" time="0"><skipped message="not yet"/></testcase>
</testsuite></testsuites>""")
        res = tp.get_runner(RUNNER).read_results(str(tmp_path), 1)
        assert res.verdict == "fail" and res.counts == {"pass": 1, "fail": 1, "unknown": 0, "skip": 1}
        bad = next(t for t in res.tests if t["name"] == "test_bad")
        assert bad["message"] == "AssertionError: assert 1 == 2" and bad["elapsed_s"] == 1.25
        assert tp.get_runner(RUNNER).read_results(str(tmp_path / "none"), None).verdict == "error"

    def test_dry_run_through_the_run_manager(self, project):
        """The engine runs whatever the runner plans: pytest collects the tests."""
        run = tp.RUNS.start(str(project), TEST, dryrun=True)
        st = _wait(project, run["id"])
        assert run["runner"] == RUNNER
        try:
            import temporalio  # noqa: F401
        except ImportError:
            # Without the SDK the tests cannot even be collected -- and the run says why.
            assert st["verdict"] == "fail", st
            assert any("temporalio" in line for line in st["all_lines"])
        else:
            assert st["verdict"] == "skip", st


def _wait(root, run_id, timeout=240):
    deadline = time.time() + timeout
    lines, since = [], 0
    while time.time() < deadline:
        st = tp.RUNS.status(str(root), run_id, since)
        lines += st["lines"]
        since = st["next"]
        if st["run_state"] == "done":
            st["all_lines"] = lines
            return st
        time.sleep(0.3)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


# ---- a live run: Temporal dev server + worker + a real gRPC service ---------

def _have_temporal():
    try:
        import temporalio  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("TEMPORAL_CLI")) and os.path.isfile(os.environ["TEMPORAL_CLI"])


@pytest.fixture
def hello_server():
    """hello.v1.HelloService on a free local port; its address."""
    import grpc
    out = tempfile.mkdtemp()
    subprocess.run([sys.executable, "-m", "grpc_tools.protoc", f"-I{os.path.dirname(HELLO_PROTO)}",
                    f"--python_out={out}", f"--grpc_python_out={out}", HELLO_PROTO],
                   check=True, capture_output=True)
    sys.path.insert(0, out)
    try:
        import hello_pb2
        import hello_pb2_grpc
    finally:
        sys.path.remove(out)

    class Hello(hello_pb2_grpc.HelloServiceServicer):
        def Greet(self, request, context):
            return hello_pb2.GreetResponse(message=f"Hello, {request.name}!")

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    hello_pb2_grpc.add_HelloServiceServicer_to_server(Hello(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield f"127.0.0.1:{port}"
    server.stop(0)


@pytest.mark.skipif(not _have_temporal(), reason="needs temporalio and TEMPORAL_CLI")
def test_live_run_calls_the_service_through_a_workflow(project, hello_server):
    _write(project, "workflows/greet.py", '''from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from activities.hello import hello_service


@workflow.defn
class Greet:
    @workflow.run
    async def run(self, name: str) -> str:
        res = await workflow.execute_activity(hello_service.greet, {"name": name},
                                              start_to_close_timeout=timedelta(seconds=30))
        return res["message"]
''')
    _write(project, "tests/greet_test.py", '''from activities.hello import ACTIVITIES
from workflows.greet import Greet


def test_greet(temporal):
    assert temporal(Greet.run, "bench", workflows=[Greet], activities=ACTIVITIES) == "Hello, bench!"
''')
    tp.set_run_settings(str(project), {"python": sys.executable, "env": {
        "HELLO_ADDR": hello_server, "TEMPORAL_CLI": os.environ["TEMPORAL_CLI"]}})
    st = _wait(project, tp.RUNS.start(str(project), "")["id"])
    assert st["verdict"] == "pass", "\n".join(st["all_lines"][-40:])
    names = {t["name"] for t in st["tests"]}
    assert {"test_greet", "test_hello_is_reachable"} <= names, names
