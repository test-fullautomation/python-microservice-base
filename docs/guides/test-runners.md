# Adding a test runner

A Manager GUI **test project** is a folder the GUI exports services into
and runs tests in. Which test framework the project uses is its
**runner**, named in `testproject.json`. The engine, the run manager, the
bridge and the GUI know nothing about any framework; everything specific
to one is a single class implementing
`MicroserviceBase.ports.test_project.TestProjectRunner` (ADR-032).

Two runners ship with MicroserviceBase:

| Runner id | Class | Tests | Results |
|---|---|---|---|
| `robotframework-aio` | `adapters/test_project/robot_aio.py` `RobotAioRunner` | `.robot` suites, `*.flow.json` flows | `output.xml` |
| `temporal-python` | `adapters/test_project/temporal.py` `TemporalPythonRunner` | pytest files running Temporal workflows | JUnit XML |

The Temporal runner exists to prove the interface: read it next to the
Robot one when writing a third.

## Who does what

```text
 GUI (app.js)              bridge (/api/test-project/*)          engine.py / runs.py           your runner
 ───────────               ───────────────────────────           ───────────────────           ───────────
 Initialize dialog  ─────► describe ───────────────────────────► available_runners, detect ──► structure(), detect()
 project view       ─────► tree ───────────────────────────────► kinds, run hints ───────────► file_types(), file_kind(), file_run_hint()
 Export             ─────► export (plan / apply) ──────────────► hashes, conflicts, protos ──► service_files(), init_files()
 Check / Save       ─────► file/check, file/save ──────────────► JSON check ─────────────────► check_syntax()
 New test / flow    ─────► suite, flow ────────────────────────► names, folders, safety ─────► suite_template(), flow_template()
 Run                ─────► run ────────────────────────────────► spawns, console, Stop ──────► can_run(), run_plan(), read_results()
 Grid / Diagram tab ─────► file/views, view-edit ──────────────► (passes through) ───────────► file_views(), inspect_file(), edit_view()
```

The engine keeps the rules every runner shares: the manifest, copying
protos, the per-file plan (`new`, `update`, `unchanged`, `edited locally`,
`kept`) and never overwriting a local edit, path safety, the run folders,
the console, *Stop* and the results view.

## The interface

Required:

| Method | Returns |
|---|---|
| `runner_id`, `display_name` | Stable id stored in `testproject.json`; the name the GUI shows. |
| `default_layout()` | `{role: folder}`; must contain `"proto"`. Projects may override folders in their manifest. |
| `init_files(layout, project_name, consul_addr)` | Files written when a folder is initialized (never over existing ones). |
| `service_files(layout, export, create_starter=)` | `PlannedFile`s for one exported service: role `generated` (refreshed by every export) or `starter` (written once, then the user's). `export` has the service's protos or reflection descriptors. |
| `run_hint(layout, export)` | Command that runs the service's starter test, shown after an export. |

Optional — each default does nothing runner-specific, so a runner opts in:

| Method / attribute | What the GUI gets |
|---|---|
| `description` | One sentence in the *Initialize* dialog. |
| `structure(layout)` | `[[path, note], ...]` drawn as the project tree in the *Initialize* dialog. |
| `detect(root)` | `{"count", "summary"}` of this runner's files in a folder; the dialog names it and preselects the runner. |
| `file_types()` | `FileType(kind, suffix, title, noun, folder, creatable)`: the sidebar groups (`suite`, `flow`, `resource`, …) and their titles, the *New …* forms' words, suffix and folder, which new files may be saved. |
| `file_kind(layout, rel)` | The kind of one file when a suffix is not enough (`tests/x_test.py` vs `activities/x.py`). |
| `generated_stamp` | Regex of a line in generated files ignored when comparing (a generation date), so re-exports of an unchanged API stay `unchanged`. |
| `check_syntax(rel, text)` | `[{"line", "message"}]` for *Check* and every save. |
| `file_run_hint(layout, rel)` | The *Run command* button's command. |
| `suite_template(...)`, `flow_template(...)` | Content of a new test / flow; returning `""` hides the *New …* button. |
| `can_debug(rel)` | The run can be debugged: `RunOptions.debug_port` is then set, and the runner adds its debug listener (Robot: `flow_debug.py`), which connects to the bridge's `debugging.py`. |
| `define(root, layout, rel, content, name, settings)` | Go to Definition: the file and line where `name` (as called in `content`) is defined. |
| `can_run(rel)`, `run_plan(...)` | What has a ▶, and the exact process: `RunPlan(argv, cwd, env, artifacts, stop_file)`. The engine spawns it and keeps the console; with `stop_file`, *Stop* creates that file and waits before killing. |
| `read_results(output_dir, returncode)` | `RunResult(verdict, counts, tests, message)` in runner-neutral words (`pass`, `fail`, `unknown`, `skip`, `error`). |
| `file_views`, `inspect_file`, `edit_view` | Extra tabs next to a file's text, drawn by a GUI plugin (`robot-grid`, `flow-graph`, `code`). |
| `group_env`, `group_views`, `inspect_group` | Run groups: processes started together, and their combined view. |
| `advisories`, `project_run_hint` | Notes before an export; the command that runs the whole project. |

## Registering it

Inside MicroserviceBase: `register_runner(MyRunner())` in
`adapters/test_project/engine.py`, next to the two built-ins.

From another package — nothing in MicroserviceBase changes — declare an
entry point; the engine loads it the first time runners are listed:

```toml
# pyproject.toml of your package
[project.entry-points."microservicebase.test_runners"]
pytest-bdd = "my_runner.runner:PytestBddRunner"
```

Install the package into the interpreter that runs the bridge and restart
the bridge. A runner that fails to import is skipped and noted in
`MicroserviceBase.adapters.test_project.PLUGIN_ERRORS`; an entry point never
replaces a runner that is already registered.

## What the generated code may rely on

The tests run with the interpreter in the project's *Run settings*, not the
bridge's. Generated code can import `MicroserviceBase` (the Temporal
activities use `adapters.grpc_bridge.reflect_client` for the calls) and
should find services the way the Robot resources do: **by name through
Consul** (`CONSUL_ADDR`), never by a host and port baked into a file —
Nomad gives a service a new port on every placement. Prefer the copied
protos (`export.proto_rel_dir`) and fall back to server reflection.

## Testing a runner

`pytest/TestProject/test_TestProjectTemporal.py` is the pattern: describe /
init / export through the engine, the tree's kinds and groups, the syntax
check, new files, the run plan, results from a sample report, a dry run
through the run manager, the entry-point loading — and a live run that
starts the framework for real. The GUI probe
`test/gui/test_gui_project_runners.js` drives the *Initialize* dialog and
the project view of a non-Robot project with real input.
