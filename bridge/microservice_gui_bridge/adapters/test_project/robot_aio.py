"""Robot Framework AIO adapter for test projects.

Layout (all folders configurable in ``testproject.json``)::

    <project>/
      testproject.json                      manifest (runner-neutral)
      testsuites/
        config/robot_config.jsonp           RF AIO config, level 3 (starter)
        <service>_smoke.robot               starter suite (starter)
      resources/<service>/<grpc>.resource   generated keywords (generated)
      proto/<service>/*.proto               copied protos, when available

Conventions followed from ``RobotFramework_TestsuitesManagement``:

* suites import the library ``WITH NAME testsuites`` and call
  ``testsuites.testsuite_setup`` / ``testsuite_teardown``;
* configuration level 3 -- ``config/robot_config.jsonp`` next to the
  suites -- is found without arguments; keys under ``params.global``
  become global Robot variables (``${CONSUL_ADDR}``).

Resources come from :mod:`MicroserviceBase.adapters.scaffold.robot_tmpl`,
the same generator as the CLI and the GUI's Robot Resource Generator.
They connect through Consul by service name, so no host/port is baked in
-- Nomad assigns a new port on every placement.

Running: ``.robot`` suites, flow files (``*.flow.json``, run with the
RobotFramework AIO fork's ``--parser robot.flow``) and the whole suites
folder. The process is ``robot_boot.py`` (``python -m robot`` that the GUI
can stop gracefully); the outcome is read from ``output.xml``, UNKNOWN
included.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import sys
from typing import Dict, List

from ...ports.test_project import (
    POSITION_FILE,
    PlannedFile,
    RunGroup,
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
    emit_resources,
    keyword_name,
    parse_proto_folder,
    resource_file_name,
    services_from_file_descriptors,
)

_CONFIG_REL = "config/robot_config.jsonp"

# Flow files (the RobotFramework AIO fork's ``robot.flow`` parser): a test
# plan drawn as a graph, built into a suite at run time.
FLOW_SUFFIX = ".flow.json"
# robot.flow.signals' store of a run, in its output folder (ROBOT_FLOW_SIGNALS).
SIGNALS_FILE = "signals.json"
_BOOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "robot_boot.py")
_INSPECT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flow_inspect.py")
# Suites and resources as a grid: rows, and the keyword each calls (robot_grid.py).
_GRID = os.path.join(os.path.dirname(os.path.abspath(__file__)), "robot_grid.py")
_GRID_SUFFIXES = (".robot", ".resource")
_VARIABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STATUS = {"PASS": "pass", "FAIL": "fail", "SKIP": "skip", "NOT RUN": "skip", "UNKNOWN": "unknown"}


def _last_status(element):
    """The element's own ``<status>`` (the last direct child of that name)."""
    found = None
    for child in element:
        if child.tag == "status":
            found = child
    return found


def _elapsed(status) -> float:
    """Seconds from a ``<status>``: ``elapsed`` (RF 7) or start/end times (older)."""
    if status is None:
        return 0.0
    if status.get("elapsed"):
        try:
            return round(float(status.get("elapsed")), 3)
        except ValueError:
            return 0.0
    import datetime as _dt
    try:
        fmt = "%Y%m%d %H:%M:%S.%f"
        start = _dt.datetime.strptime(status.get("starttime", ""), fmt)
        end = _dt.datetime.strptime(status.get("endtime", ""), fmt)
        return round((end - start).total_seconds(), 3)
    except ValueError:
        return 0.0


def _ident(name: str) -> str:
    """``hello-gui`` -> ``hello_gui``: safe as file stem and connection name."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "service"


def _config_jsonp(project_name: str, consul_addr: str) -> str:
    return (
        "// RobotFramework AIO configuration for this test project.\n"
        "//\n"
        "// Found automatically at configuration level 3 (config/robot_config.jsonp\n"
        "// next to the suites). Keys under params.global become global Robot\n"
        "// variables, e.g. ${CONSUL_ADDR}.\n"
        "//\n"
        "// Created by Microservice Manager and never overwritten by it: edit freely.\n"
        "{\n"
        f'  "Project"       : {json.dumps(project_name)},\n'
        f'  "WelcomeString" : {json.dumps(project_name + ": microservice tests")},\n'
        '  "TargetName"    : "bench",\n'
        '  "params"        : {\n'
        '    "global" : {\n'
        f'      "CONSUL_ADDR" : {json.dumps(consul_addr)}\n'
        "    }\n"
        "  }\n"
        "}\n"
    )


# ---- where the members of a run group meet ------------------------------------
#
# Flows that run side by side meet through the bench: one publishes a value
# with ``Set Signal <name> <value>``, another waits for it at a gate on the
# same signal (``Signal Should Be <name> == <value>``). That is read from the
# flows, not declared, so only these two shapes are recognised: a keyword
# step named "Set Signal", and a gate whose first argument is a signal some
# other member sets (with ``==`` its value must match too).

_VAR_REF_RE = re.compile(r"\$\{([^}]+)\}")


def _norm(name: str) -> str:
    """Robot's name matching: case, spaces and underscores do not count."""
    return re.sub(r"[\s_]+", "", str(name)).lower()


def _resolve(value, values: Dict[str, str]) -> str:
    table = {_norm(k): v for k, v in values.items()}
    return _VAR_REF_RE.sub(lambda m: str(table.get(_norm(m.group(1)), m.group(0))), str(value))


def _same_value(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        return a.strip() == b.strip()


def _walk_steps(steps):
    for step in steps or []:
        yield step
        for key in ("body", "recovery", "yes", "no"):
            yield from _walk_steps(step.get(key))


def _flow_steps(flow: dict):
    for phase in [flow.get("setup")] + list(flow.get("tests") or []) + [flow.get("teardown")]:
        if phase:
            yield from _walk_steps(phase.get("steps"))


def sync_links(members: List[dict]) -> List[dict]:
    """Where run-group members meet: ``[{"from": {"member", "node"},
    "to": {"member", "node"}, "label"}]`` -- a ``Set Signal`` step of one
    member that a gate of another member waits for.

    ``members``: ``[{"id", "flow", "values"}]``, ``values`` being the
    variables the member runs with (file defaults, then its own).
    """
    writes, waits = [], []
    for m in members:
        for step in _flow_steps(m["flow"]):
            args = [_resolve(a, m.get("values") or {}) for a in step.get("args") or []]
            if step.get("kind") == "keyword" and _norm(step.get("keyword", "")) == "setsignal" and len(args) >= 2:
                writes.append((m["id"], step["id"], args[0], args[1]))
            elif step.get("kind") == "gate" and args:
                value = args[2] if len(args) >= 3 and args[1] == "==" else None
                waits.append((m["id"], step["id"], args[0], value))
    links = []
    for w_member, w_node, name, value in writes:
        for g_member, g_node, g_name, g_value in waits:
            if g_member == w_member or g_name != name:
                continue
            if g_value is not None and not _same_value(g_value, value):
                continue
            links.append({"from": {"member": w_member, "node": w_node},
                          "to": {"member": g_member, "node": g_node},
                          "label": f"{name} = {value}"})
    return links


class RobotAioRunner(TestProjectRunner):
    """Robot Framework AIO (``RobotFramework_TestsuitesManagement``)."""

    runner_id = "robotframework-aio"
    display_name = "Robot Framework AIO"

    def default_layout(self) -> Dict[str, str]:
        return {"suites": "testsuites", "resources": "resources", "proto": "proto"}

    def _config_path(self, layout: Dict[str, str]) -> str:
        return f"{layout['suites']}/{_CONFIG_REL}"

    def _suite_path(self, layout: Dict[str, str], export: ServiceExport) -> str:
        return f"{layout['suites']}/{_ident(export.consul_name)}_smoke.robot"

    def init_files(self, layout, project_name, consul_addr):
        return {self._config_path(layout): _config_jsonp(project_name, consul_addr)}

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
                f"API description of {export.consul_name}."
            )
        return unique

    def service_files(self, layout, export, *, create_starter=True) -> List[PlannedFile]:
        services = self._services(export)
        res_dir = f"{layout['resources']}/{export.consul_name}"
        files = [PlannedFile(f"{res_dir}/{name}", content, "generated")
                 for name, content in emit_resources(services).items()]
        if create_starter:
            files.append(PlannedFile(self._suite_path(layout, export),
                                     self._starter_suite(layout, export, services, res_dir),
                                     "starter"))
            files.append(PlannedFile(self._config_path(layout),
                                     _config_jsonp(export.project_name, export.consul_addr),
                                     "starter"))
        return files

    def advisories(self, root, layout, export) -> List[str]:
        rel = self._config_path(layout)
        path = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(path):
            return []
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return []
        match = re.search(r'"CONSUL_ADDR"\s*:\s*"([^"]*)"', text)
        if match is None:
            return [f"{rel} does not define CONSUL_ADDR under params.global; suites fall "
                    f"back to {export.consul_addr}. Add it there to point every suite at "
                    "the right Consul."]
        if export.consul_addr and match.group(1).rstrip("/") != export.consul_addr.rstrip("/"):
            return [f"{rel} points suites at Consul {match.group(1)}, but "
                    f"{export.consul_name} is registered in {export.consul_addr}."]
        return []

    def run_hint(self, layout, export) -> str:
        return f"python -m robot -d results {self._suite_path(layout, export)}"

    def project_run_hint(self, layout) -> str:
        return f"python -m robot -d results {layout['suites']}"

    # ---- running ---------------------------------------------------------

    def can_run(self, rel_path: str) -> bool:
        lower = str(rel_path).lower()
        return lower == "" or lower.endswith(".robot") or lower.endswith(FLOW_SUFFIX)

    def run_plan(self, root, layout, target, settings: RunSettings, options: RunOptions,
                 output_dir) -> RunPlan:
        if not self.can_run(target):
            raise TestProjectError(f"{target} is not a Robot suite or a flow file.")
        target_abs = os.path.join(root, *(target or layout["suites"]).split("/"))
        if not os.path.exists(target_abs):
            raise TestProjectError(f"Nothing to run at {target or layout['suites']}.")

        python = settings.python.strip() or sys.executable
        if os.path.isabs(python) and not os.path.isfile(python):
            raise TestProjectError(f"The interpreter in the run settings does not exist: {python}")

        argv = [python, _BOOT, "--outputdir", output_dir,
                "--consolecolors", "off", "--consolemarkers", "off", "--consolewidth", "100"]
        if self._uses_flows(target_abs):
            argv += ["--parser", "robot.flow"]
        for name, value in sorted((options.variables or {}).items()):
            if not _VARIABLE_RE.match(name):
                raise TestProjectError(f"Invalid variable name {name!r}: use letters, digits and '_'.")
            argv += ["--variable", f"{name}:{value}"]
        if options.dryrun:
            argv.append("--dryrun")
        argv += [str(a) for a in settings.args]
        argv.append(target_abs)

        env = self._env(root, settings)
        stop_file = os.path.join(output_dir, ".stop")
        env["MM_RUN_STOP_FILE"] = stop_file
        if self._uses_flows(target_abs):
            # The fork's robot.flow.signals: this run's own store (a group run
            # shares one, see group_env). The settings' environment wins.
            if "ROBOT_FLOW_SIGNALS" not in (settings.env or {}):
                env["ROBOT_FLOW_SIGNALS"] = os.path.join(output_dir, SIGNALS_FILE)
            if not options.dryrun:
                # Where the run is in its flow, for the live Diagram (flow_position.py).
                env["MM_FLOW_POSITION"] = os.path.join(output_dir, POSITION_FILE)
        return RunPlan(
            argv=argv, cwd=root, env=env, stop_file=stop_file,
            artifacts=[RunArtifact("log.html", "Log", primary=True),
                       RunArtifact("report.html", "Report"),
                       RunArtifact("output.xml", "output.xml")],
        )

    @staticmethod
    def _env(root: str, settings: RunSettings) -> Dict[str, object]:
        """Environment changes for the project's interpreter (None = remove)."""
        paths = [p if os.path.isabs(p) else os.path.normpath(os.path.join(root, p))
                 for p in settings.pythonpath if str(p).strip()]
        if os.environ.get("PYTHONPATH"):
            paths.append(os.environ["PYTHONPATH"])
        env = {
            "PYTHONPATH": os.pathsep.join(paths) or None,
            # A codec suffix (utf-8:surrogateescape) crashes Robot's console
            # writer as soon as it reports an error.
            "PYTHONIOENCODING": None,
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
        }
        env.update({str(k): str(v) for k, v in (settings.env or {}).items()})
        return env

    # ---- flow files: Diagram and Robot views -------------------------------

    def file_views(self, rel_path: str) -> List[Dict[str, str]]:
        lower = str(rel_path).lower()
        if lower.endswith(FLOW_SUFFIX):
            return [{"id": "diagram", "title": "Diagram", "type": "flow-graph"},
                    {"id": "robot", "title": "Robot", "type": "code", "language": "robot"}]
        if lower.endswith(_GRID_SUFFIXES):
            return [{"id": "grid", "title": "Grid", "type": "robot-grid"}]
        return []

    def inspect_file(self, root, layout, rel_path, content, settings: RunSettings):
        """Ask the tools themselves, with the project's interpreter and path:
        for a flow, the fork (``flow_inspect.py``), so the diagram shows exactly
        the structure the run will build -- and refuses what the run would
        refuse; for a suite or resource, Robot's parser and Libdoc
        (``robot_grid.py``), so every keyword resolves as it will at run time."""
        if not self.file_views(rel_path):
            return {"ok": False, "error": f"{rel_path} has no extra views."}
        if str(rel_path).lower().endswith(_GRID_SUFFIXES):
            data = self._run_helper(_GRID, root, rel_path, content, settings, "the file")
            if not data.get("ok"):
                return {k: data.get(k) for k in ("ok", "error", "node", "line", "missing")}
            return {"ok": True, "views": {"grid": {k: data.get(k) for k in ("grid", "keywords", "imports", "catalog", "catalog_list", "variables", "features")}}}
        data = self._inspect_flow(root, rel_path, content, settings)
        if not data.get("ok"):
            return {k: data.get(k) for k in ("ok", "error", "node", "line", "missing")}
        return {"ok": True, "views": {"diagram": {"flow": data["flow"]},
                                      "robot": {"text": data["robot"]}}}

    def _inspect_flow(self, root, rel_path, content, settings: RunSettings) -> dict:
        """``flow_inspect.py``'s answer for ``content`` (the text of ``rel_path``)."""
        return self._run_helper(_INSPECT, root, rel_path, content, settings, "the flow")

    def edit_view(self, root, layout, rel_path, content, view_id, edit, settings: RunSettings):
        """A step changed in the Grid: Robot's own model applies it (``robot_grid.py
        --edit``), so what the edit does not touch is written back as it was.
        A step dropped or changed in a flow's Diagram: ``flow_inspect.py --edit``
        rewires the flow and has the fork's validator accept it first."""
        lower = str(rel_path).lower()
        payload = json.dumps({"text": content, "edit": edit})
        if view_id == "diagram" and lower.endswith(FLOW_SUFFIX):
            data = self._run_helper(_INSPECT, root, rel_path, payload, settings, "the edit", flags=["--edit"])
            return {k: data.get(k) for k in ("ok", "text", "node", "error", "missing") if k in data}
        if view_id != "grid" or not lower.endswith(_GRID_SUFFIXES):
            return {"ok": False, "error": f"{rel_path} is not edited in a {view_id} view."}
        data = self._run_helper(_GRID, root, rel_path, payload, settings, "the edit", flags=["--edit"])
        return {k: data.get(k) for k in ("ok", "text", "line", "error", "missing") if k in data}

    def _run_helper(self, script, root, rel_path, content, settings: RunSettings, what, flags=()) -> dict:
        """Run a helper script with the project's interpreter and path; its JSON answer."""
        import subprocess
        python = settings.python.strip() or sys.executable
        env = dict(os.environ)
        for key, value in self._env(root, settings).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        full = os.path.join(root, *str(rel_path).split("/"))
        try:
            proc = subprocess.run(
                [python, script, *flags, full], input=content.encode("utf-8"), capture_output=True,
                cwd=root, env=env, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": f"Could not ask {python} about {what}: {exc}"}
        try:
            data = json.loads(proc.stdout.decode("utf-8", errors="replace") or "null")
        except ValueError:
            data = None
        if not isinstance(data, dict):
            tail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()[-3:]
            return {"ok": False, "error": f"{what[0].upper() + what[1:]} could not be read: " +
                                          (" / ".join(tail) or f"exit {proc.returncode}")}
        return data

    # ---- run groups: every member's flow, and where they meet ----------------

    def group_env(self, run_dir: str) -> Dict[str, str]:
        """The members of a group run meet in one signal store of that run."""
        return {"ROBOT_FLOW_SIGNALS": os.path.join(run_dir, SIGNALS_FILE)}

    def group_views(self, group: RunGroup) -> List[Dict[str, str]]:
        if group.members and all(m.target.lower().endswith(FLOW_SUFFIX) for m in group.members):
            return [{"id": "sync", "title": "Diagram", "type": "flow-group"}]
        return []

    def inspect_group(self, root, layout, group: RunGroup, settings: RunSettings):
        if not self.group_views(group):
            return {"ok": False, "error": "Only groups of flow files can be drawn.", "member": None}
        flows: Dict[str, dict] = {}
        members = []
        for m in group.members:
            if m.target not in flows:
                path = os.path.join(root, *m.target.split("/"))
                with open(path, encoding="utf-8-sig", errors="replace") as fh:
                    flows[m.target] = self._inspect_flow(root, m.target, fh.read(), settings)
            data = flows[m.target]
            if not data.get("ok"):
                out = {k: data.get(k) for k in ("ok", "error", "node", "line", "missing")}
                out.update(member=m.id, error=f"{m.id} ({m.target}): {data.get('error')}")
                return out
            values = dict(data["flow"].get("variables") or {})
            values.update(m.variables)
            members.append({"id": m.id, "target": m.target, "variables": m.variables,
                            "values": values, "flow": data["flow"]})
        links = sync_links(members)
        for member in members:
            member.pop("values")
        return {"ok": True, "views": {"sync": {"members": members, "links": links}}}

    @staticmethod
    def _uses_flows(path: str) -> bool:
        if os.path.isfile(path):
            return path.lower().endswith(FLOW_SUFFIX)
        for _dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if d not in ("results", "__pycache__", ".git")]
            if any(f.lower().endswith(FLOW_SUFFIX) for f in filenames):
                return True
        return False

    def read_results(self, output_dir, returncode) -> RunResult:
        xml_path = os.path.join(output_dir, "output.xml")
        if not os.path.isfile(xml_path):
            return RunResult("error", message=(
                "Stopped before Robot Framework wrote output.xml." if returncode is None else
                f"Robot Framework ended with code {returncode} without writing output.xml; "
                "the console shows why."))
        try:
            import xml.etree.ElementTree as ET
            top = ET.parse(xml_path).getroot().find("suite")
        except Exception as exc:   # noqa: BLE001 -- a half-written file after a kill
            return RunResult("error", message=f"output.xml could not be read: {exc}")
        if top is None:
            return RunResult("error", message="output.xml holds no suite.")

        tests: List[dict] = []

        def walk(suite, chain):
            chain = chain + [suite.get("name", "")]
            for child in suite:
                if child.tag == "suite":
                    walk(child, chain)
                elif child.tag == "test":
                    status = _last_status(child)
                    tests.append({
                        "name": child.get("name", ""),
                        "suite": ".".join(chain),
                        "status": _STATUS.get(status.get("status", ""), "unknown") if status is not None else "unknown",
                        "message": (status.text or "").strip() if status is not None else "",
                        "elapsed_s": _elapsed(status),
                    })

        walk(top, [])
        counts = {"pass": 0, "fail": 0, "unknown": 0, "skip": 0}
        for t in tests:
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        suite_status = _last_status(top)
        if counts["fail"]:
            verdict = "fail"
        elif counts["unknown"]:
            verdict = "unknown"
        elif counts["pass"]:
            verdict = "pass"
        elif counts["skip"]:
            verdict = "skip"
        else:
            verdict = _STATUS.get(suite_status.get("status", "") if suite_status is not None else "", "error")
        message = ""
        if suite_status is not None and (suite_status.text or "").strip():
            message = suite_status.text.strip().splitlines()[0]
        if returncode is None:
            message = "Stopped on request. " + message
        return RunResult(verdict, counts, tests, message.strip())

    def flow_template(self, layout, flow_path, name, resource_paths) -> str:
        """A flow that runs as it is: one test, one step to replace -- so its
        Diagram draws at once and Edit flow can take it from there."""
        here = posixpath.dirname(flow_path)
        imports = [posixpath.relpath(p, here or ".") for p in resource_paths]
        data = {
            "flow": {"name": name, "version": 1},
            **({"imports": {"resources": imports}} if imports else {}),
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "test", "kind": "phase", "role": "test", "name": name},
                {"id": "first", "kind": "keyword", "keyword": "Log",
                 "args": ["Replace me: open the Diagram tab and use Edit flow to add steps."]},
                {"id": "end", "kind": "end"},
            ],
            "edges": [["start", "test"], ["test", "first"], ["first", "end"]],
        }
        lines = ["{"]
        for key in ("flow", "imports"):
            if key in data:
                lines.append(f'  "{key}": {json.dumps(data[key], ensure_ascii=False)},')
        lines.append('  "nodes": [')
        lines += [f"    {json.dumps(n, ensure_ascii=False)}," for n in data["nodes"]]
        lines[-1] = lines[-1].rstrip(",")
        lines.append("  ],")
        lines.append('  "edges": [')
        lines += [f"    {json.dumps(e)}," for e in data["edges"]]
        lines[-1] = lines[-1].rstrip(",")
        lines.append("  ]")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def suite_template(self, layout, suite_path, service, resource_paths,
                       consul_addr, proto_rel_dir) -> str:
        suites_dir = posixpath.dirname(suite_path)
        stem = posixpath.splitext(posixpath.basename(suite_path))[0]
        title = re.sub(r"[_-]+", " ", stem).strip().title() or "New Suite"

        # Resource stem -> keyword prefix + connection name, the same mapping
        # the generator uses (hello_service.resource -> "Hello Service").
        conns = []
        for res in resource_paths:
            res_stem = posixpath.splitext(posixpath.basename(res))[0]
            conns.append((res_stem.replace("_", " ").title(), res_stem))

        lines = [
            "*** Settings ***",
            f"Documentation     {title}.",
            "Library           RobotFramework_TestsuitesManagement    WITH NAME    testsuites",
        ]
        lines += [f"Resource          {posixpath.relpath(res, suites_dir)}" for res in resource_paths]
        if conns:
            lines += ["Suite Setup       Open Service Connections",
                      "Suite Teardown    Close Service Connections"]
        else:
            lines += ["Suite Setup       testsuites.testsuite_setup",
                      "Suite Teardown    testsuites.testsuite_teardown"]
        if conns:
            proto_value = ("${CURDIR}/" + posixpath.relpath(proto_rel_dir, suites_dir)
                           if proto_rel_dir else "${EMPTY}")
            lines += [
                "",
                "*** Variables ***",
                "# CONSUL_ADDR normally comes from config/robot_config.jsonp; this is the fallback.",
                f"${{CONSUL_ADDR}}      {consul_addr}",
                f"${{SERVICE_NAME}}     {service}",
                f"${{PROTO_DIR}}        {proto_value}",
            ]
        lines += [
            "",
            "*** Test Cases ***",
            f"{title} Works",
            "    [Documentation]    Describe what this test checks.",
            "    No Operation",
        ]
        if conns:
            lines += ["", "*** Keywords ***", "Open Service Connections", "    testsuites.testsuite_setup"]
            for prefix, conn in conns:
                lines += [f"    {prefix} Open Connection    {conn}",
                          "    ...    service_name=${SERVICE_NAME}    consul_addr=${CONSUL_ADDR}    proto_dir=${PROTO_DIR}"]
            lines += ["", "Close Service Connections"]
            lines += [f"    Run Keyword And Ignore Error    {prefix} Close Connection    {conn}"
                      for prefix, conn in conns]
            lines.append("    testsuites.testsuite_teardown")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------

    def _starter_suite(self, layout, export, services, res_dir) -> str:
        suites = layout["suites"]

        def rel(target: str) -> str:
            return posixpath.relpath(target, suites)

        # Connection name = resource stem (HelloService -> hello_service), so
        # it reads the same as the generator's file naming.
        conns = [(svc, resource_file_name(svc)[:-len(".resource")]) for svc in services]
        if export.proto_rel_dir:
            proto_note = "# The service's protos, copied into the project; used when it has no server reflection."
            proto_value = "${CURDIR}/" + rel(export.proto_rel_dir)
        else:
            proto_note = "# No .proto was copied: the service is reached through server reflection."
            proto_value = "${EMPTY}"

        lines: List[str] = [
            "*** Settings ***",
            f"Documentation     Starter suite for the ``{export.consul_name}`` service.",
            "...               Created by Microservice Manager and never overwritten by it: edit freely.",
            f"...               Run from the project root:  {self.run_hint(layout, export)}",
            "Library           RobotFramework_TestsuitesManagement    WITH NAME    testsuites",
        ]
        lines += [f"Resource          {rel(f'{res_dir}/{resource_file_name(svc)}')}" for svc in services]
        lines += [
            "Suite Setup       Open Service Connections",
            "Suite Teardown    Close Service Connections",
            "",
            "*** Variables ***",
            "# CONSUL_ADDR normally comes from config/robot_config.jsonp (params.global);",
            "# this value is only the fallback.",
            f"${{CONSUL_ADDR}}      {export.consul_addr}",
            f"${{SERVICE_NAME}}     {export.consul_name}",
            proto_note,
            f"${{PROTO_DIR}}        {proto_value}",
            "",
            "*** Test Cases ***",
            f"{export.consul_name} Is Reachable",
            "    [Documentation]    The suite setup resolved the service through Consul and opened",
            "    ...                a connection; replace this with real checks.",
            "    No Operation",
        ]

        svc0, conn0 = conns[0]
        methods = [m for m in svc0.methods if not m.server_streaming] or list(svc0.methods)
        if methods:
            method = methods[0]
            args = "".join(f"    {p.name}=<{p.type}>" for p in method.params)
            lines += [
                f"    # Example -- call {method.name}, then check the result:",
                f"    # ${{res}}=    {keyword_name(svc0, method)}    {conn0}{args}",
                "    # Log    ${res}",
            ]

        lines += ["", "*** Keywords ***", "Open Service Connections", "    testsuites.testsuite_setup"]
        for svc, conn in conns:
            lines += [
                f"    {keyword_name(svc)} Open Connection    {conn}",
                "    ...    service_name=${SERVICE_NAME}    consul_addr=${CONSUL_ADDR}    proto_dir=${PROTO_DIR}",
            ]
        lines += ["", "Close Service Connections"]
        lines += [f"    Run Keyword And Ignore Error    {keyword_name(svc)} Close Connection    {conn}"
                  for svc, conn in conns]
        lines.append("    testsuites.testsuite_teardown")
        return "\n".join(lines) + "\n"
