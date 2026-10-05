"""Temporal (Python SDK) adapter for test projects.

Tests are pytest files that run Temporal workflows; the workflows call the
exported services through generated activities. Layout (all folders
configurable in ``testproject.json``)::

    <project>/
      testproject.json                       manifest (runner-neutral)
      conftest.py                            Temporal server + worker for tests (starter)
      pytest.ini                             test discovery (starter)
      activities/<service>/__init__.py       ACTIVITIES of the service (generated)
      activities/<service>/<grpc>.py         one activity per RPC (generated)
      workflows/<service>_smoke.py           starter workflow (starter)
      tests/<service>_smoke_test.py          starter test (starter)
      proto/<service>/*.proto                copied protos, when available

The generated activities reach the service the way the Robot resources do:
by name through Consul (``CONSUL_ADDR``), so no host/port is baked in, and
through its protos or, without them, server reflection
(:mod:`MicroserviceBase.adapters.grpc_bridge.reflect_client`).

Running: ``python -m pytest`` on a test file or the tests folder, results
from its JUnit XML. ``conftest.py`` connects to ``TEMPORAL_ADDRESS`` when it
is set (the project's run settings), else starts a local Temporal dev server
(``temporal`` CLI: ``TEMPORAL_CLI``, or downloaded by the SDK on first use).
*Stop* lets the running test finish and skips the rest.
"""

from __future__ import annotations

import datetime as _dt
import os
import posixpath
import re
import sys
from typing import Dict, List, Optional

from ...ports.test_project import (
    FileType,
    PlannedFile,
    RunArtifact,
    RunOptions,
    RunPlan,
    RunResult,
    RunSettings,
    ServiceExport,
    TestProjectError,
    TestProjectRunner,
)
from ..scaffold.robot_tmpl import (
    RobotGenError,
    _snake,
    parse_proto_folder,
    services_from_file_descriptors,
)

JUNIT_FILE = "junit.xml"
_TEST_FILE_RE = re.compile(r"^(test_.*|.*_test)\.py$", re.I)
_VARIABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Python reserved words cannot be function names.
_KEYWORDS = {"and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del",
             "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in",
             "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while",
             "with", "yield", "none", "true", "false"}


def _ident(name: str) -> str:
    """``hello-gui`` -> ``hello_gui``: a Python module name."""
    ident = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "service"
    return f"s_{ident}" if ident[0].isdigit() else ident


def _func(name: str) -> str:
    func = _snake(name)
    return f"{func}_" if func in _KEYWORDS else func


def _camel(text: str) -> str:
    camel = "".join(w[:1].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]+", text) if w)
    return camel if camel and not camel[0].isdigit() else f"W{camel}"


def _module(rel_path: str) -> str:
    """``activities/hello_gui/__init__.py`` -> ``activities.hello_gui``."""
    path = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    parts = [p for p in path.split("/") if p]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


_CONFTEST = '''"""Temporal for this project's tests.

Created by Microservice Manager and never overwritten by it: edit freely.

* ``TEMPORAL_ADDRESS`` (host:port) -- use that Temporal server, namespace
  ``TEMPORAL_NAMESPACE``; set both in the GUI's *Run settings*.
* otherwise a local dev server is started for each test run: the
  ``temporal`` CLI at ``TEMPORAL_CLI`` when set, else the SDK downloads it
  once (that needs internet access).

A test runs a workflow with ``temporal(Workflow.run, arg, workflows=[...],
activities=[...])``: a worker with those workflows and activities serves a
fresh task queue while the workflow runs, and its result is returned.
"""

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TEMPORAL_CLI = os.environ.get("TEMPORAL_CLI", "")


async def _connect():
    from temporalio.client import Client
    from temporalio.testing import WorkflowEnvironment
    if TEMPORAL_ADDRESS:
        return None, await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    env = await WorkflowEnvironment.start_local(
        namespace=TEMPORAL_NAMESPACE, dev_server_existing_path=TEMPORAL_CLI or None)
    return env, env.client


def run_workflow(run, *args, workflows, activities=(), timeout_s=120):
    """Run one workflow to its end with a worker for it; its result."""
    from temporalio.worker import Worker

    async def scenario():
        env, client = await _connect()
        try:
            queue = f"mm-test-{uuid.uuid4().hex[:12]}"
            with ThreadPoolExecutor(max_workers=8) as pool:
                async with Worker(client, task_queue=queue, workflows=list(workflows),
                                  activities=list(activities), activity_executor=pool):
                    return await client.execute_workflow(
                        run, *args, id=f"{queue}-run", task_queue=queue,
                        execution_timeout=timedelta(seconds=timeout_s))
        finally:
            if env is not None:
                await env.shutdown()

    return asyncio.run(scenario())


@pytest.fixture
def temporal():
    """``temporal(Workflow.run, *args, workflows=[...], activities=[...])``."""
    return run_workflow


def pytest_runtest_setup(item):
    """*Stop* in the Manager GUI: the running test ends, the rest are skipped."""
    stop = os.environ.get("MM_RUN_STOP_FILE")
    if stop and os.path.exists(stop):
        pytest.exit("Stopped on request.", returncode=2)
'''

_PYTEST_INI = """# Test discovery for this project. Created by Microservice Manager and never
# overwritten by it: edit freely.
[pytest]
testpaths = {tests}
python_files = test_*.py *_test.py
"""

_REQUIREMENTS = """# What the tests need, besides MicroserviceBase (gRPC + Consul helpers).
temporalio>=1.7
pytest>=7
"""


class TemporalPythonRunner(TestProjectRunner):
    """Temporal workflows, run by pytest with the Temporal Python SDK."""

    runner_id = "temporal-python"
    display_name = "Temporal (Python SDK)"
    description = ("pytest tests that run Temporal workflows; generated activities per "
                   "service reach it through Consul.")
    # A generated module carries its generation date in its docstring.
    generated_stamp = r"^Generated: .*\n?"

    def default_layout(self) -> Dict[str, str]:
        return {"tests": "tests", "workflows": "workflows", "activities": "activities",
                "proto": "proto"}

    # ---- files ---------------------------------------------------------------

    def file_types(self) -> List[FileType]:
        return [
            FileType("suite", "_test.py", "Tests", "test", "tests", creatable=True),
            FileType("flow", ".py", "Workflows", "workflow", "workflows", creatable=True),
            FileType("resource", ".py", "Activities", "activities module", "activities"),
        ]

    def file_kind(self, layout: Dict[str, str], rel_path: str) -> str:
        rel = str(rel_path)
        base = posixpath.basename(rel)
        if not base.lower().endswith(".py"):
            return ""
        if base == "conftest.py":
            return "config"
        if _TEST_FILE_RE.match(base):
            return "suite"
        for kind, key in (("flow", "workflows"), ("resource", "activities")):
            folder = layout.get(key, key)
            if rel.startswith(folder + "/"):
                return kind
        return ""

    def structure(self, layout: Dict[str, str]) -> List[List[str]]:
        return [
            ["testproject.json", "manifest: runner, layout, what was exported"],
            ["conftest.py", "Temporal server and worker for the tests (TEMPORAL_ADDRESS)"],
            [f"{layout['activities']}/<service>/*.py", "generated activities — refreshed on export"],
            [f"{layout['workflows']}/<service>_smoke.py", "starter workflow per service — yours to edit"],
            [f"{layout['tests']}/<service>_smoke_test.py", "starter test per service — yours to edit"],
            [f"{layout['proto']}/<service>/*.proto", "copied protos, when available"],
        ]

    def detect(self, root: str) -> Dict[str, object]:
        from .engine import walk_files
        count = 0
        for dirpath, files in walk_files(root):
            for name in files:
                if not name.endswith(".py"):
                    continue
                try:
                    with open(os.path.join(dirpath, name), encoding="utf-8", errors="replace") as fh:
                        if "temporalio" in fh.read(64_000):
                            count += 1
                except OSError:
                    pass
        if not count:
            return {}
        return {"count": count,
                "summary": f"{count} Python file{'' if count == 1 else 's'} using temporalio"}

    def check_syntax(self, rel_path: str, content: str) -> List[Dict[str, object]]:
        if not str(rel_path).lower().endswith(".py"):
            return []
        try:
            compile(content, rel_path, "exec", dont_inherit=True)
        except SyntaxError as exc:
            return [{"line": exc.lineno or 1, "message": f"{type(exc).__name__}: {exc.msg}"}]
        except ValueError as exc:   # e.g. NUL bytes
            return [{"line": 1, "message": str(exc)}]
        return []

    def init_files(self, layout, project_name, consul_addr):
        return {"conftest.py": _CONFTEST,
                "pytest.ini": _PYTEST_INI.format(tests=layout["tests"]),
                "requirements.txt": _REQUIREMENTS}

    # ---- export ----------------------------------------------------------------

    def _services(self, export: ServiceExport):
        try:
            if export.proto_dir:
                services = parse_proto_folder(export.proto_dir)
            else:
                services = services_from_file_descriptors(
                    export.file_descriptors or [], source_label="server reflection")
        except RobotGenError as exc:
            raise TestProjectError(str(exc)) from exc
        wanted = set(export.grpc_services or [])
        if wanted:
            services = [s for s in services if s.full_name in wanted or s.name in wanted]
        unique, seen = [], set()
        for svc in services:
            if svc.full_name not in seen:
                seen.add(svc.full_name)
                unique.append(svc)
        if not unique:
            raise TestProjectError(
                "None of the gRPC services "
                f"({', '.join(sorted(wanted)) or 'none advertised'}) were found in the "
                f"API description of {export.consul_name}.")
        return unique

    def service_files(self, layout, export, *, create_starter=True) -> List[PlannedFile]:
        services = self._services(export)
        ident = _ident(export.consul_name)
        pkg = f"{layout['activities']}/{ident}"
        modules = [(svc, _func(svc.name)) for svc in services]
        files = [PlannedFile(f"{pkg}/{mod}.py", self._activities_module(layout, export, svc, pkg),
                             "generated") for svc, mod in modules]
        files.append(PlannedFile(f"{pkg}/__init__.py", self._package(export, modules), "generated"))
        if create_starter:
            files.append(PlannedFile(self._workflow_path(layout, export),
                                     self._starter_workflow(layout, export, services), "starter"))
            files.append(PlannedFile(self._test_path(layout, export),
                                     self._starter_test(layout, export), "starter"))
            for rel, content in self.init_files(layout, export.project_name,
                                                export.consul_addr).items():
                files.append(PlannedFile(rel, content, "starter"))
        return files

    def _workflow_path(self, layout, export) -> str:
        return f"{layout['workflows']}/{_ident(export.consul_name)}_smoke.py"

    def _test_path(self, layout, export) -> str:
        return f"{layout['tests']}/{_ident(export.consul_name)}_smoke_test.py"

    def run_hint(self, layout, export) -> str:
        return f"python -m pytest {self._test_path(layout, export)}"

    def project_run_hint(self, layout) -> str:
        return f"python -m pytest {layout['tests']}"

    def file_run_hint(self, layout, rel_path) -> str:
        return f"python -m pytest {rel_path}"

    def _activities_module(self, layout, export: ServiceExport, svc, pkg: str) -> str:
        if export.proto_rel_dir:
            depth = len(pkg.split("/"))
            proto = ("os.path.join(os.path.dirname(os.path.abspath(__file__)), "
                     + ", ".join(['".."'] * depth) + f", {export.proto_rel_dir!r})")
            proto_note = "# The service's protos, copied into the project; used when it has no server reflection."
        else:
            proto = '""'
            proto_note = "# No .proto was copied: the service is reached through server reflection."
        env_addr = re.sub(r"[^A-Z0-9]+", "_", export.consul_name.upper()).strip("_") + "_ADDR"
        lines = [
            f'"""Temporal activities for {svc.full_name} of the ``{export.consul_name}`` service.',
            "",
            "Generated by Microservice Manager from the service's API and refreshed on",
            "every export: put your own activities in another module.",
            f"Generated: {_dt.date.today().isoformat()}",
            '"""',
            "",
            "import json",
            "import os",
            "import urllib.parse",
            "import urllib.request",
            "from typing import Any, Dict, Optional",
            "",
            "from temporalio import activity",
            "",
            f"SERVICE_NAME = {export.consul_name!r}",
            f"GRPC_SERVICE = {svc.full_name!r}",
            f"CONSUL_ADDR = os.environ.get(\"CONSUL_ADDR\", {export.consul_addr!r})",
            "# host:port that skips Consul, e.g. for a service started by hand.",
            f"ADDRESS_VARIABLE = {env_addr!r}",
            proto_note,
            f"PROTO_DIR = {proto}",
            "",
            "",
            "def resolve() -> str:",
            '    """host:port of a passing instance of the service, from Consul."""',
            "    if os.environ.get(ADDRESS_VARIABLE):",
            "        return os.environ[ADDRESS_VARIABLE]",
            "    url = (CONSUL_ADDR.rstrip(\"/\") + \"/v1/health/service/\"",
            "           + urllib.parse.quote(SERVICE_NAME) + \"?passing=true\")",
            "    with urllib.request.urlopen(url, timeout=5) as resp:",
            "        entries = json.loads(resp.read().decode(\"utf-8\"))",
            "    for entry in entries:",
            "        svc, node = entry.get(\"Service\") or {}, entry.get(\"Node\") or {}",
            "        address = svc.get(\"Address\") or node.get(\"Address\")",
            "        if address and svc.get(\"Port\"):",
            "            return f\"{address}:{svc['Port']}\"",
            "    raise RuntimeError(f\"{SERVICE_NAME} has no passing instance in Consul {CONSUL_ADDR}.\")",
            "",
            "",
            "def call(method: str, request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:",
            '    """Call one RPC of the service with a JSON-like request; the response as a dict."""',
            "    from MicroserviceBase.adapters.grpc_bridge.reflect_client import (",
            "        GrpcReflectClient, LocalProtoClient)",
            "    target = resolve()",
            "    client = (LocalProtoClient.from_search_paths(target, [PROTO_DIR])",
            "              if PROTO_DIR and os.path.isdir(PROTO_DIR) else GrpcReflectClient(target))",
            "    try:",
            "        return client.call_unary(GRPC_SERVICE, method, json.dumps(request or {}))",
            "    finally:",
            "        client.close()",
            "",
            "",
            f'@activity.defn(name="{svc.name}.reachable")',
            "def reachable() -> str:",
            '    """Where the service is (host:port): it is registered and passing in Consul."""',
            "    return resolve()",
        ]
        used = {"reachable", "resolve", "call"}
        for rpc in svc.methods:
            func = _func(rpc.name)
            while func in used:
                func += "_"
            used.add(func)
            params = ", ".join(f"{p.name}: {p.type}" for p in rpc.params) or "no fields"
            kind = "server stream: the first events" if rpc.server_streaming else "unary"
            lines += [
                "",
                "",
                f'@activity.defn(name="{svc.name}.{rpc.name}")',
                f"def {func}(request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:",
                f'    """{rpc.name}({params}) -> {rpc.return_type} ({kind})."""',
                f"    return call({rpc.name!r}, request)",
            ]
        return "\n".join(lines) + "\n"

    def _package(self, export: ServiceExport, modules) -> str:
        lines = [
            f'"""Activities of the ``{export.consul_name}`` service, for a worker:',
            "``Worker(..., activities=ACTIVITIES)``.",
            "",
            "Generated by Microservice Manager and refreshed on every export.",
            f"Generated: {_dt.date.today().isoformat()}",
            '"""',
            "",
        ]
        lines += [f"from . import {mod}" for _svc, mod in modules]
        lines += ["", "ACTIVITIES = ["]
        for svc, mod in modules:
            funcs, used = ["reachable"], {"reachable", "resolve", "call"}
            for rpc in svc.methods:
                func = _func(rpc.name)
                while func in used:
                    func += "_"
                used.add(func)
                funcs.append(func)
            lines += [f"    {mod}.{f}," for f in funcs]
        lines.append("]")
        return "\n".join(lines) + "\n"

    def _starter_workflow(self, layout, export: ServiceExport, services) -> str:
        ident = _ident(export.consul_name)
        cls = _camel(export.consul_name) + "Smoke"
        svc0 = services[0]
        mod0 = _func(svc0.name)
        pkg = _module(f"{layout['activities']}/{ident}/__init__.py")
        lines = [
            f'"""Starter workflow for the ``{export.consul_name}`` service.',
            "",
            "Created by Microservice Manager and never overwritten by it: edit freely.",
            f"Run from the project root:  {self.run_hint(layout, export)}",
            '"""',
            "",
            "from datetime import timedelta",
            "",
            "from temporalio import workflow",
            "",
            "with workflow.unsafe.imports_passed_through():",
            f"    from {pkg} import {mod0}",
            "",
            "STEP = timedelta(seconds=30)",
            "",
            "",
            "@workflow.defn",
            f"class {cls}:",
            "    @workflow.run",
            "    async def run(self) -> str:",
            "        # The service is registered and passing in Consul; replace with real checks.",
            f"        where = await workflow.execute_activity({mod0}.reachable, start_to_close_timeout=STEP)",
        ]
        methods = [m for m in svc0.methods if not m.server_streaming] or list(svc0.methods)
        if methods:
            rpc = methods[0]
            fields = ", ".join(f'"{p.name}": <{p.type}>' for p in rpc.params)
            lines += [
                f"        # Example -- call {rpc.name}, then check the result:",
                f"        # res = await workflow.execute_activity({mod0}.{_func(rpc.name)}, {{{fields}}},",
                "        #                                       start_to_close_timeout=STEP)",
            ]
        lines.append("        return where")
        return "\n".join(lines) + "\n"

    def _starter_test(self, layout, export: ServiceExport) -> str:
        ident = _ident(export.consul_name)
        cls = _camel(export.consul_name) + "Smoke"
        return "\n".join([
            f'"""Starter test for the ``{export.consul_name}`` service.',
            "",
            "Created by Microservice Manager and never overwritten by it: edit freely.",
            '"""',
            "",
            f"from {_module(layout['activities'] + '/' + ident + '/__init__.py')} import ACTIVITIES",
            f"from {_module(self._workflow_path(layout, export))} import {cls}",
            "",
            "",
            f"def test_{ident}_is_reachable(temporal):",
            f"    where = temporal({cls}.run, workflows=[{cls}], activities=ACTIVITIES)",
            "    assert where",
        ]) + "\n"

    def suite_template(self, layout, suite_path, service, resource_paths,
                       consul_addr, proto_rel_dir) -> str:
        stem = posixpath.basename(suite_path)[: -len(".py")]
        name = re.sub(r"^test_|_test$", "", stem) or "new"
        title = re.sub(r"[_-]+", " ", name).strip().capitalize() or "New test"
        lines = [f'"""{title}."""', ""]
        packages = sorted({_module(p) for p in resource_paths if p.endswith("/__init__.py")})
        if service and packages:
            lines += [f"from {packages[0]} import ACTIVITIES", ""]
        lines += [
            "",
            f"def test_{_func(name)}(temporal):",
            '    """Describe what this test checks."""',
            "    # result = temporal(MyWorkflow.run, workflows=[MyWorkflow], activities=ACTIVITIES)"
            if service and packages else
            "    # result = temporal(MyWorkflow.run, workflows=[MyWorkflow], activities=[...])",
            "    # assert result == ...",
        ]
        return "\n".join(lines) + "\n"

    def flow_template(self, layout, flow_path, name, resource_paths) -> str:
        cls = _camel(name)
        imports = []
        for path in resource_paths:
            if not path.endswith(".py"):
                continue
            mod = _module(path)
            if "." in mod:
                parent, leaf = mod.rsplit(".", 1)
                imports.append(f"    from {parent} import {leaf}")
            else:
                imports.append(f"    import {mod}")
        lines = [
            f'"""{name}: a workflow."""',
            "",
            "from datetime import timedelta",
            "",
            "from temporalio import workflow",
            "",
        ]
        if imports:
            lines += ["with workflow.unsafe.imports_passed_through():", *imports, ""]
        lines += [
            "STEP = timedelta(seconds=30)",
            "",
            "",
            "@workflow.defn",
            f"class {cls}:",
            "    @workflow.run",
            "    async def run(self) -> str:",
            "        # Call activities here, e.g.:",
            "        # res = await workflow.execute_activity(module.activity, request, start_to_close_timeout=STEP)",
            '        return "done"',
        ]
        return "\n".join(lines) + "\n"

    # ---- running -----------------------------------------------------------------

    def can_run(self, rel_path: str) -> bool:
        rel = str(rel_path)
        return rel == "" or bool(_TEST_FILE_RE.match(posixpath.basename(rel)))

    def run_plan(self, root, layout, target, settings: RunSettings, options: RunOptions,
                 output_dir) -> RunPlan:
        if not self.can_run(target):
            raise TestProjectError(f"{target} is not a test file (test_*.py or *_test.py).")
        target_abs = os.path.join(root, *(target or layout["tests"]).split("/"))
        if not os.path.exists(target_abs):
            raise TestProjectError(f"Nothing to run at {target or layout['tests']}.")
        python = settings.python.strip() or sys.executable
        if os.path.isabs(python) and not os.path.isfile(python):
            raise TestProjectError(f"The interpreter in the run settings does not exist: {python}")

        argv = [python, "-m", "pytest", target_abs, "-v", "--color=no", "-p", "no:cacheprovider",
                f"--junitxml={os.path.join(output_dir, JUNIT_FILE)}", f"--rootdir={root}"]
        if options.dryrun:
            argv.append("--collect-only")
        argv += [str(a) for a in settings.args]

        paths = [root] + [p if os.path.isabs(p) else os.path.normpath(os.path.join(root, p))
                          for p in settings.pythonpath if str(p).strip()]
        if os.environ.get("PYTHONPATH"):
            paths.append(os.environ["PYTHONPATH"])
        env: Dict[str, Optional[str]] = {"PYTHONPATH": os.pathsep.join(paths),
                                         "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        # Variables reach the tests as environment variables (os.environ["NAME"]).
        for name, value in sorted((options.variables or {}).items()):
            if not _VARIABLE_RE.match(name):
                raise TestProjectError(f"Invalid variable name {name!r}: use letters, digits and '_'.")
            env[name] = str(value)
        env.update({str(k): str(v) for k, v in (settings.env or {}).items()})
        stop_file = os.path.join(output_dir, ".stop")
        env["MM_RUN_STOP_FILE"] = stop_file
        return RunPlan(argv=argv, cwd=root, env=env, stop_file=stop_file,
                       artifacts=[RunArtifact(JUNIT_FILE, "JUnit XML", primary=True)])

    def read_results(self, output_dir, returncode) -> RunResult:
        path = os.path.join(output_dir, JUNIT_FILE)
        if not os.path.isfile(path):
            return RunResult("error", message=(
                "Stopped before pytest wrote its results." if returncode is None else
                f"pytest ended with code {returncode} without writing {JUNIT_FILE}; "
                "the console shows why."))
        try:
            import xml.etree.ElementTree as ET
            top = ET.parse(path).getroot()
        except Exception as exc:   # noqa: BLE001 -- a half-written file after a kill
            return RunResult("error", message=f"{JUNIT_FILE} could not be read: {exc}")
        tests: List[dict] = []
        for case in top.iter("testcase"):
            status, message = "pass", ""
            for child in case:
                if child.tag in ("failure", "error"):
                    status = "fail"
                    message = (child.get("message") or child.text or "").strip()
                    break
                if child.tag == "skipped":
                    status = "skip"
                    message = (child.get("message") or "").strip()
            try:
                elapsed = round(float(case.get("time") or 0), 3)
            except ValueError:
                elapsed = 0.0
            tests.append({"name": case.get("name", ""), "suite": case.get("classname", ""),
                          "status": status, "message": message.splitlines()[0] if message else "",
                          "elapsed_s": elapsed})
        counts = {"pass": 0, "fail": 0, "unknown": 0, "skip": 0}
        for t in tests:
            counts[t["status"]] += 1
        message = ""
        if counts["fail"]:
            verdict = "fail"
        elif counts["pass"]:
            verdict = "pass"
        elif counts["skip"]:
            verdict = "skip"
        elif returncode in (0, 5):   # 5: pytest collected no test
            verdict, message = "skip", "No test ran (collected only, or none found)."
        else:
            verdict = "error"
            message = f"pytest ended with code {returncode}; the console shows why."
        if returncode is None:
            message = "Stopped on request. " + message
        return RunResult(verdict, counts, tests, message.strip())
