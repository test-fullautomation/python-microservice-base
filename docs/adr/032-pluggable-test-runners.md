# ADR-032: Pluggable test runners for test projects

## Status

Proposed

## Date

2026-10-05

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- (pending)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-10-05 | 1.0 | Initial version: runner owns file types, detection, syntax check and run command; entry-point discovery; Temporal runner as the second implementation |

## Context

ADR-029 made Robot Framework the primary test client, and the Manager GUI's
test projects were built for it: the GUI exports a service into a folder as
generated keyword resources and a starter suite, edits and checks the
suites, and runs them.

A port for runners already existed
(`MicroserviceBase/ports/test_project.py`, `TestProjectRunner`): export,
templates, run plan and results went through it. But Robot Framework still
leaked past it in a dozen places:

- the engine decided file kinds by suffix (`.robot` → suite, `.resource` →
  resource, `.flow.json` → flow) and allowed only those as new files;
- *Check* tokenized with `robot.api` whatever the project;
- the folder detection counted `.robot` files and looked for
  `robot_config.jsonp`;
- the re-export comparison stripped a Robot documentation line;
- new suites were always `<suites>/<name>.robot`, new flows
  `flows/<name>.flow.json`;
- run names stripped `.robot` / `.flow.json`;
- the GUI hard-coded the Robot project tree in the *Initialize* dialog, the
  default runner, the group titles (*Suites*, *Resources*), the `.robot`
  suffix in the *New suite* form and `python -m robot -d results` as every
  file's run command;
- the only way to add a runner was to edit `engine.py`.

Teams want other frameworks for the same services — for example Temporal
workflows (`temporalio`) for long-running, resumable test orchestration —
without forking the GUI.

## Decision

1. **Everything framework-specific lives in the runner.** The port gains
   optional methods with neutral defaults: `file_types()` (kind, suffix,
   title, noun, folder, creatable) and `file_kind()`, `structure()`,
   `detect()`, `check_syntax()`, `file_run_hint()`, `description` and
   `generated_stamp`. The engine asks the runner; its own table covers only
   files any project may hold (`.proto`, `.json`, `.py`, `.md`, …).
2. **The GUI renders what the runner says.** `describe` returns each
   runner's description and project structure and per-runner detection;
   `tree` returns the project's `kinds` (groups and their words),
   `can_new_suite` / `can_new_flow` and a `run_hint` per file. The GUI
   draws groups, *New …* forms, the *Initialize* tree and the run command
   from these, with the old Robot values only as fallbacks.
3. **Runners from other packages** are entry points in the group
   `microservicebase.test_runners`, loaded on first use. A broken one is
   skipped and recorded; none replaces a registered runner.
4. **A second runner ships** to keep the interface honest:
   `temporal-python` — pytest tests running Temporal workflows, generated
   activities that call the service through Consul and the copied protos or
   reflection, JUnit XML results, *Stop* through the stop file. It runs end
   to end in the tests against a real Temporal dev server and gRPC service.
5. A project's runner is fixed at initialization; converting a project to
   another runner is out of scope (initialize a new one and export again).

## Consequences

### Positive

- A new framework is one class, in this repository or in its own package,
  with no change to the engine, the bridge or the GUI.
- The shared rules — manifest, proto copies, plan/apply without clobbering
  local edits, path safety, run folders, console, *Stop*, results — are
  written once and hold for every runner.
- Robot Framework projects behave as before; their manifests and recorded
  hashes are unchanged.

### Negative

- `describe()['detected']` changed shape (`{runner_id: {count, summary}}`
  instead of `robot_suites` / `aio_config`); callers outside the GUI must
  follow.
- Run ids now cut a target's name at its first dot
  (`a.b.robot` → `a`, was `a.b`).
- Rich file views (Grid, Diagram) remain per runner: a new framework gets
  the text editor until it adds its own view plugin.
- Generated code imports `MicroserviceBase`, so the tests' interpreter must
  have it (as Robot projects need QConnectBase).

## Alternatives considered

- **A runner-agnostic generic process runner** (any command line, any
  report format): too little for the GUI's starter files, checks and
  results; it would leave every runner-specific decision to the user.
- **Separate GUIs per framework:** duplicates the export safety rules and
  the run manager, and splits the bench workflow.

## Related

- ADR-029 — Robot Framework as the primary test client (still the default
  runner).
- Guide: *Adding a test runner* (`docs/guides/test-runners.md`).
