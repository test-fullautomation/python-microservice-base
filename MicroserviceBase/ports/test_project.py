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
# *******************************************************************************
#
# File: test_project.py
#
# Description:
#
#   Port for test-runner adapters used by test projects.
#
#   A test project is a folder the Manager GUI exports services into. The
#   runner-neutral core (adapters/test_project/engine.py) owns the manifest,
#   proto discovery and safe planning/writing; a runner adapter owns what is
#   generated and where it goes. Supporting another test runner means one
#   new implementation of TestProjectRunner, registered with the engine.
#
#   Running is optional and runner-neutral too: a runner that implements
#   can_run / run_plan / read_results gets the GUI's Run button, live
#   console and results view. The engine spawns exactly the command the
#   runner plans; the GUI only ever sees RunPlan artifacts and RunResult.
#
# *******************************************************************************

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class TestProjectError(RuntimeError):
   """
Raised for any test-project failure the user can act on (bad folder,
not initialized, nothing to generate from, unsafe path, ...).
   """

   __test__ = False   # not a pytest test class


class TestProjectConflict(TestProjectError):
   """
Raised when a file changed on disk since the caller read it, so saving
would silently discard someone else's change.
   """

   __test__ = False   # not a pytest test class


@dataclass
class PlannedFile:
   """
One file an export intends to write.

**Attributes:**

* ``path``

  / *Type*: str /

  Project-relative path with forward slashes.

* ``content``

  / *Type*: str /

  Full file content.

* ``role``

  / *Type*: str /

  ``"generated"`` -- owned by the tool: regenerated on every export, but
  never over a local edit unless the user allows it.
  ``"starter"`` -- created once when missing, then owned by the user and
  never touched again.
   """

   path: str
   content: str
   role: str


@dataclass
class ServiceExport:
   """
Everything a runner needs to produce files for one service.

Exactly one of ``proto_dir`` / ``file_descriptors`` describes the API.

**Attributes:**

* ``consul_name`` -- Consul service name, also the per-service folder name.
* ``consul_addr`` -- Consul the service is registered in.
* ``grpc_services`` -- fully-qualified gRPC service names to export.
* ``proto_dir`` -- folder holding exactly the protos that will be copied
  into the project (staged by the engine), or ``None``.
* ``proto_rel_dir`` -- project-relative folder those protos land in, or
  ``None`` when no protos are copied.
* ``file_descriptors`` -- ``FileDescriptorProto`` list (server reflection)
  when no proto is available, else ``None``.
* ``project_name`` -- folder name of the project.
   """

   consul_name: str
   consul_addr: str
   grpc_services: List[str] = field(default_factory=list)
   proto_dir: Optional[str] = None
   proto_rel_dir: Optional[str] = None
   file_descriptors: Optional[list] = None
   project_name: str = ""


@dataclass
class RunSettings:
   """
How a project's tests are started, stored under ``"run"`` in
``testproject.json`` and edited in the GUI.

**Attributes:**

* ``python`` -- interpreter to run with; empty means the bridge's own.
* ``pythonpath`` -- folders put in front of ``PYTHONPATH``; relative ones
  are relative to the project root (e.g. a runner checkout's ``src``).
* ``args`` -- extra command-line arguments added to every run.
* ``env`` -- extra environment variables for every run.
   """

   python: str = ""
   pythonpath: List[str] = field(default_factory=list)
   args: List[str] = field(default_factory=list)
   env: Dict[str, str] = field(default_factory=dict)


@dataclass
class RunOptions:
   """
Per-run choices made when starting a run.

* ``variables`` -- ``{name: value}`` handed to the tests.
* ``dryrun`` -- check the tests without executing them, when supported.
* ``resources`` -- record RAM and CPU of the run's processes (the engine's
  monitor, ``resources.html``); not for a dry run.
   """

   variables: Dict[str, str] = field(default_factory=dict)
   dryrun: bool = False
   resources: bool = False


@dataclass
class GroupMember:
   """
One process of a run group.

* ``id`` -- short name, unique in the group (``IVI``); also its results folder.
* ``target`` -- project-relative file it runs.
* ``variables`` -- ``{name: value}`` for this process only.
   """

   id: str
   target: str
   variables: Dict[str, str] = field(default_factory=dict)


@dataclass
class RunGroup:
   """
Processes that run at the same time and meet through the bench -- e.g. one
flow run twice with different variables, each waiting for the other.
Stored under ``"groups"`` in ``testproject.json``.

* ``id`` -- unique in the project; names its runs.
* ``title`` -- what the GUI calls it.
* ``members`` -- the processes, started together.
* ``env`` -- environment for every member. ``${RUN_DIR}`` in a value is the
  run's own folder (a fresh meeting place per run), ``${PROJECT_DIR}`` the
  project root.
   """

   id: str
   title: str = ""
   members: List[GroupMember] = field(default_factory=list)
   env: Dict[str, str] = field(default_factory=dict)


@dataclass
class RunArtifact:
   """
A file a run leaves in its output folder that the GUI can open.

* ``name`` -- file name inside the output folder (``log.html``).
* ``label`` -- what the GUI calls it (``Log``).
* ``primary`` -- the one to open first.
   """

   name: str
   label: str
   primary: bool = False


#: Entry-point group through which other packages add test runners: each
#: entry point names a :class:`TestProjectRunner` subclass (or a factory
#: returning an instance), e.g. in ``pyproject.toml``::
#:
#:    [project.entry-points."microservicebase.test_runners"]
#:    my-runner = "my_package.runner:MyRunner"
RUNNER_ENTRY_POINTS = "microservicebase.test_runners"


#: A run's live position, in its output folder: which node of its flow each
#: process is in, written by the runner as it goes (JSON: ``node``,
#: ``counts``, ``last``, ``done``, ``seq``). Optional; the engine passes it on
#: with the run's status, and the GUI lights that node in the Diagram.
POSITION_FILE = "flow_position.json"


@dataclass
class RunPlan:
   """
The exact process a run starts. The engine spawns ``argv`` in ``cwd``
with ``env`` merged over its own environment (a value of ``None``
removes that variable) and keeps the console output.

``stop_file``: when set, *Stop* first creates this file and gives the
process a grace period to finish on its own (teardowns, reports) before
it is killed. Without it, *Stop* kills at once. A runner that can tell
where the run is writes :data:`POSITION_FILE` into its output folder.
   """

   argv: List[str]
   cwd: str
   env: Dict[str, Optional[str]] = field(default_factory=dict)
   artifacts: List[RunArtifact] = field(default_factory=list)
   stop_file: str = ""


@dataclass
class RunResult:
   """
What a finished run found, in runner-neutral terms.

* ``verdict`` -- ``"pass"`` | ``"fail"`` | ``"unknown"`` | ``"skip"`` |
  ``"error"`` (the run itself broke: nothing was reported).
* ``counts`` -- ``{"pass": n, "fail": n, "unknown": n, "skip": n}``.
* ``tests`` -- one ``{"name", "suite", "status", "message",
  "elapsed_s"}`` per test, ``status`` using the verdict words.
* ``message`` -- one line for the GUI when there is something to say.
   """

   verdict: str
   counts: Dict[str, int] = field(default_factory=dict)
   tests: List[Dict[str, object]] = field(default_factory=list)
   message: str = ""


@dataclass
class FileType:
   """
A kind of file a runner works with, so the engine and the GUI never need
to know the runner's file names.

* ``kind`` -- what the GUI groups it under: ``"suite"`` (something that
  runs: a test file), ``"flow"`` (a test drawn as a graph), ``"resource"``
  (reusable steps the tests import), ``"config"``, ``"library"``.
* ``suffix`` -- how a file of that kind is recognised (``".robot"``); the
  longest matching suffix wins. ``""`` for a kind found by
  :meth:`TestProjectRunner.file_kind` alone.
* ``title`` -- the GUI's heading for the group (``"Suites"``).
* ``noun`` -- one of them, for buttons and messages (``"suite"``).
* ``folder`` -- layout key of the folder new files of this kind go to.
* ``creatable`` -- the GUI may create files of this kind (with the
  runner's :meth:`~TestProjectRunner.suite_template` or
  :meth:`~TestProjectRunner.flow_template`) and save new ones.
   """

   kind: str
   suffix: str = ""
   title: str = ""
   noun: str = ""
   folder: str = ""
   creatable: bool = False


class TestProjectRunner(ABC):
   """
A test runner the Manager GUI can export services for -- and, when it
implements the run methods, run tests with.

Everything runner-specific -- file names, layout, generated code, syntax
checks, the run command, how results are read -- lives in the
implementation; the engine, the run manager and the GUI only use this
interface. A runner is registered with
``MicroserviceBase.adapters.test_project.register_runner`` or, from another
package, as an entry point in the group :data:`RUNNER_ENTRY_POINTS`.
   """

   __test__ = False   # not a pytest test class

   #: Stable id stored in ``testproject.json`` (e.g. ``"robotframework-aio"``).
   runner_id: str = ""
   #: Human-readable name for the GUI.
   display_name: str = ""
   #: One sentence for the GUI's runner choice.
   description: str = ""
   #: Regular expression (multi-line) of a line in generated files that is
   #: ignored when telling whether a file changed -- e.g. a generation date,
   #: so two exports of the same API on different days compare equal.
   generated_stamp: str = ""

   # ---- files (optional; the defaults know nothing runner-specific) ----------

   def file_types(self) -> List[FileType]:
      """
The kinds of files this runner works with. Files of no listed kind fall
back to the engine's generic ones (``.proto``, ``.json``, ``.py``, ``.md``
...). Default: none.
      """
      return []

   def file_kind(self, layout: Dict[str, str], rel_path: str) -> str:
      """
The kind of the project file ``rel_path``, or ``""`` to let the engine
decide. Default: the longest matching suffix of :meth:`file_types`.
Override when a suffix is not enough (``tests/test_x.py`` is a test,
``activities/x.py`` is not).
      """
      lower = str(rel_path).lower()
      best = None
      for ft in self.file_types():
         if ft.suffix and lower.endswith(ft.suffix.lower()):
            if best is None or len(ft.suffix) > len(best.suffix):
               best = ft
      return best.kind if best else ""

   def structure(self, layout: Dict[str, str]) -> List[List[str]]:
      """
What a project of this runner looks like, for the GUI's *Initialize*
dialog: ``[[path, note], ...]``, ``<service>`` standing for a service's
name. Default: none.
      """
      return []

   def detect(self, root: str) -> Dict[str, object]:
      """
What of this runner a folder already holds, before it is a test project:
``{"count": n, "summary": "3 .robot files"}``, or ``{}`` for nothing.
The GUI preselects the runner that found something. Default: nothing.
      """
      return {}

   def check_syntax(self, rel_path: str, content: str) -> List[Dict[str, object]]:
      """
Syntax problems of ``content`` (unsaved text of ``rel_path``) as
``[{"line": n, "message": text}]``. JSON files are checked by the engine.
Default: none (no check).
      """
      return []

   def file_run_hint(self, layout: Dict[str, str], rel_path: str) -> str:
      """
Command that runs ``rel_path`` from the project root, for the GUI's *Run
command* button. Default: none.
      """
      return ""

   @abstractmethod
   def default_layout(self) -> Dict[str, str]:
      """
Project-relative folders keyed by role. Must contain ``"proto"`` (where
copied protos go); other keys are runner-specific.
      """

   @abstractmethod
   def init_files(self, layout: Dict[str, str], project_name: str,
                  consul_addr: str) -> Dict[str, str]:
      """
Files created when a folder is initialized as a test project, as
``{relative_path: content}``. Never overwrites an existing file.
      """

   @abstractmethod
   def service_files(self, layout: Dict[str, str], export: ServiceExport, *,
                     create_starter: bool = True) -> List[PlannedFile]:
      """
Files for one exported service (protos excluded -- the engine plans
those). Raise :class:`TestProjectError` when nothing can be generated.
      """

   def advisories(self, root: str, layout: Dict[str, str],
                  export: ServiceExport) -> List[str]:
      """
Human-readable notes about the existing project worth showing before an
export (e.g. configuration that points elsewhere). Default: none.
      """
      return []

   def project_run_hint(self, layout: Dict[str, str]) -> str:
      """
Command that runs every suite of the project, from the project root.
Default: none.
      """
      return ""

   def suite_template(self, layout: Dict[str, str], suite_path: str,
                      service: Optional[str], resource_paths: List[str],
                      consul_addr: str, proto_rel_dir: Optional[str]) -> str:
      """
Content of a new, empty test suite at ``suite_path`` -- wired to the
generated ``resource_paths`` of ``service`` when one is given. Return an
empty string when the runner cannot create suites (the default).
      """
      return ""

   def flow_template(self, layout: Dict[str, str], flow_path: str, name: str,
                     resource_paths: List[str]) -> str:
      """
Content of a new flow file at ``flow_path`` (project-relative), titled
``name`` and importing the project-relative ``resource_paths``. Return an
empty string when the runner has no flow files (the default).
      """
      return ""

   @abstractmethod
   def run_hint(self, layout: Dict[str, str], export: ServiceExport) -> str:
      """
Command that runs the exported service's starter tests, from the
project root.
      """

   # ---- running (optional) ---------------------------------------------------

   def can_run(self, rel_path: str) -> bool:
      """
Whether ``rel_path`` (a project file, or ``""`` for the whole project)
is something this runner can run. Default: nothing -- the GUI then
offers no Run button.
      """
      return False

   def run_plan(self, root: str, layout: Dict[str, str], target: str,
                settings: RunSettings, options: RunOptions,
                output_dir: str) -> RunPlan:
      """
The process that runs ``target`` (project-relative; ``""`` = the whole
project) and writes its results into ``output_dir``, which exists.
Raise :class:`TestProjectError` when it cannot be run.
      """
      raise TestProjectError(f"{self.display_name or self.runner_id} cannot run tests.")

   # ---- extra file views (optional) -------------------------------------------

   def file_views(self, rel_path: str) -> List[Dict[str, str]]:
      """
Views the GUI offers next to a file's text, as
``[{"id", "title", "type"}]``. ``type`` is what the GUI knows how to draw:
``"flow-graph"`` (a structured test flow) or ``"code"`` (read-only text,
with an optional ``"language"``). Default: none -- the file shows as text
only.
      """
      return []

   def inspect_file(self, root: str, layout: Dict[str, str], rel_path: str,
                    content: str, settings: RunSettings) -> Dict[str, object]:
      """
The data of :meth:`file_views` for ``content`` (the editor's text, saved or
not): ``{"ok": True, "views": {view_id: data}}``, or ``{"ok": False,
"error": ..., "node": <id or None>, "line": <n or None>}`` when the file
cannot be read that way. ``missing: True`` means the runner's tooling is
not available with the project's run settings.
      """
      return {"ok": False, "error": f"{self.display_name or self.runner_id} has no extra views."}

   def edit_view(self, root: str, layout: Dict[str, str], rel_path: str, content: str,
                 view_id: str, edit: Dict[str, object], settings: RunSettings) -> Dict[str, object]:
      """
Apply one edit made in a file view (e.g. a step changed in a grid) to
``content``, the text in the editor. Returns ``{"ok": True, "text": new
text, "line": where the edited part now is}`` or ``{"ok": False, "error":
...}``. The GUI puts the text into the editor as an unsaved change, so
saving, checking and conflict detection stay the editor's. Default: views
cannot edit.
      """
      return {"ok": False, "error": f"{self.display_name or self.runner_id} views cannot edit files."}

   # ---- run groups: views (optional) -----------------------------------------

   def group_env(self, run_dir: str) -> Dict[str, str]:
      """
Environment every member of a group run shares, set by the engine for that
run -- e.g. where the members meet (the RobotFramework AIO fork's
``ROBOT_FLOW_SIGNALS``: a signal store in ``run_dir``, so two runs never
see each other's signals). The group's own ``env`` wins over it. Default:
nothing.
      """
      return {}

   def group_views(self, group: RunGroup) -> List[Dict[str, str]]:
      """
Views of a run group as a whole, like :meth:`file_views`. ``"flow-group"``
draws every member's flow and how they meet. Default: none.
      """
      return []

   def inspect_group(self, root: str, layout: Dict[str, str], group: RunGroup,
                     settings: RunSettings) -> Dict[str, object]:
      """
The data of :meth:`group_views`: ``{"ok": True, "views": {view_id: data}}``
or ``{"ok": False, "error": ..., "member": <id or None>}``. For
``"flow-group"`` the data is ``{"members": [{"id", "target", "variables",
"flow"}], "links": [{"from": {"member", "node"}, "to": {"member", "node"},
"label"}]}`` -- a link is a step of one member that another member waits
for.
      """
      return {"ok": False, "error": f"{self.display_name or self.runner_id} has no group views."}

   def read_results(self, output_dir: str, returncode: Optional[int]) -> RunResult:
      """
The outcome of a finished run from what it left in ``output_dir``.
``returncode`` is ``None`` when the run was stopped. Default: the return
code alone.
      """
      if returncode is None:
         return RunResult("error", message="Stopped before it finished.")
      return RunResult("pass" if returncode == 0 else "fail")
