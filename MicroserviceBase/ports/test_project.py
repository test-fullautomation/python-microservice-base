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
   """

   variables: Dict[str, str] = field(default_factory=dict)
   dryrun: bool = False


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


@dataclass
class RunPlan:
   """
The exact process a run starts. The engine spawns ``argv`` in ``cwd``
with ``env`` merged over its own environment (a value of ``None``
removes that variable) and keeps the console output.

``stop_file``: when set, *Stop* first creates this file and gives the
process a grace period to finish on its own (teardowns, reports) before
it is killed. Without it, *Stop* kills at once.
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


class TestProjectRunner(ABC):
   """
A test runner the Manager GUI can export services for -- and, when it
implements the run methods, run tests with.
   """

   __test__ = False   # not a pytest test class

   #: Stable id stored in ``testproject.json`` (e.g. ``"robotframework-aio"``).
   runner_id: str = ""
   #: Human-readable name for the GUI.
   display_name: str = ""

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

   def read_results(self, output_dir: str, returncode: Optional[int]) -> RunResult:
      """
The outcome of a finished run from what it left in ``output_dir``.
``returncode`` is ``None`` when the run was stopped. Default: the return
code alone.
      """
      if returncode is None:
         return RunResult("error", message="Stopped before it finished.")
      return RunResult("pass" if returncode == 0 else "fail")
