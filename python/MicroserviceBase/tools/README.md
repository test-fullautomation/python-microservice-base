# `mb-scaffold` — scaffold-from-CLI

Generates microservice scaffolds by calling the bridge's
`/api/scaffold/generate-v2` endpoint — same generator the Service Creator
wizard uses, just from a terminal.

## Prerequisites

- The bridge must be running.  Easiest: start the Manager GUI (it spawns
  the bridge on `http://127.0.0.1:1112`).  For headless use:

  ```cmd
  python -m MicroserviceBase.adapters.ui_bridge.fastapi_bridge
  ```

- Optional: `pip install pyyaml` if you want YAML config files (JSON works
  out of the box).

## Quick examples

```cmd
:: Inline flags for a tiny Python service
python -m MicroserviceBase.tools.scaffold_cli ^
    --name Hello --language python --output .\out

:: Full spec in a config file
python -m MicroserviceBase.tools.scaffold_cli --config example_spec.yaml

:: Import an existing .proto and emit a monorepo
python -m MicroserviceBase.tools.scaffold_cli ^
    --name DeviceServices --proto device.proto --monorepo ^
    --language cpp --gui widget --output .\out
```

## All flags

| Flag                    | Notes                                                    |
|-------------------------|----------------------------------------------------------|
| `-c, --config FILE`     | YAML or JSON spec (all payload fields allowed)           |
| `-n, --name NAME`       | `service_name`                                           |
| `-l, --language LANG`   | `python` or `cpp`                                        |
| `--gui KIND`            | `none` / `html` / `qml` / `wasm` / `widget`              |
| `-o, --output DIR`      | Parent folder; service dir is created inside             |
| `--version STR`         | Version string (default `1.0.0`)                         |
| `--description STR`     | Free-form description                                    |
| `--proto PATH`          | Import an existing .proto (autopopulates methods)        |
| `--proto-service NAME`  | Pick one service from a multi-service .proto             |
| `--monorepo`            | One project with N executables (requires `--proto`)      |
| `--no-nomad`            | Skip the `.nomad.hcl`                                    |
| `--no-build-scripts`    | Skip `build_deploy*.bat/.sh`                             |
| `--no-stubs`            | Skip pre-generating proto stubs at generate time         |
| `--bridge-url URL`      | Bridge base URL (default `$MB_BRIDGE_URL` or localhost)  |
| `--dry-run`             | Print the JSON payload and exit                          |
| `-q, --quiet`           | Only print the created path on success                   |

## Composition rules

- The config file provides the base values.
- CLI flags override matching fields.
- `--proto` overrides `methods` / `services` / `proto_content_override` /
  `proto_package` with values parsed from the file.

So you can keep a reusable `base.yaml` (language, gui, nomad knobs, output
root) and add `--proto`, `--name`, `--monorepo` at the CLI per run.

## Exit codes

- `0` — scaffold written
- `1` — bridge reachable but generation failed (error printed to stderr)
- `SystemExit` from argparse on flag problems; from script on unreachable
  bridge or missing required fields.

---

# `robot_gen` — Robot Framework resources from a `.proto` folder

Sibling tool to `mb-scaffold`.  Given a folder of `.proto` files, emits
**one `.robot` resource per service** with typed keywords (one per RPC)
that wrap `QConnectBase.ConnectionManager` — so Robot tests can call
`Com Setup Device Service Set Interface Type    conn=power    type=0`
instead of hand-rolling JSON `send_cmd` strings.

Long-form docs (with screenshots + GUI walk-through):
[`../MicroserviceManagerGUI/docs/md/robot_generator.md`](../MicroserviceManagerGUI/docs/md/robot_generator.md).

## Prerequisites

- `grpcio-tools` installed (the tool runs `protoc` in-process).  The
  AIO Python ships it; otherwise: `pip install grpcio-tools`.
- **Does not require the bridge to be running** — the generator is
  pure in-process Python.  Safe to use from CI / a fresh terminal.

## Quick examples

```cmd
:: One service per .proto under proto/, write to robot/ alongside it
python -m MicroserviceBase.tools.robot_gen ^
    --proto-dir D:\Project\.\MultiProto2\proto ^
    --out       D:\Project\.\MultiProto2\robot

:: Only emit the resource for ComSetupDeviceService
python -m MicroserviceBase.tools.robot_gen ^
    --proto-dir .\proto ^
    --out       .\robot ^
    --service ComSetupDeviceService

:: Dump every generated resource to stdout (for diffing or piping)
python -m MicroserviceBase.tools.robot_gen --proto-dir .\proto --stdout

:: Overwrite existing files (default: skip + warn)
python -m MicroserviceBase.tools.robot_gen --proto-dir .\proto --out .\robot --force
```

## All flags

| Flag                       | Notes                                                                                          |
|----------------------------|------------------------------------------------------------------------------------------------|
| `--proto-dir DIR` (req.)   | Folder containing `*.proto` files.  Non-recursive — only top-level `.proto` files are scanned. |
| `--out DIR`                | Folder to write `.resource` files into.  Created if missing.  Required unless `--stdout`.      |
| `--service NAME`           | Repeatable.  Only emit resources for these services.  Default = all services in the folder.    |
| `--force`                  | Overwrite existing `.resource` files.  Default refuses + lists which files were skipped.       |
| `--stdout`                 | Print every generated resource to stdout, separated by a comment header.  Useful for diffs.    |

## What it produces

For every `service` block declared anywhere under `--proto-dir`, the
tool emits `<snake_service_name>.resource` containing:

- `*** Settings ***` — `Library QConnectBase.ConnectionManager` (as
  `conn_manager`) + `Library Collections`
- `*** Variables ***` — `${<SERVICE>_FQN}` carrying the fully-qualified
  proto service name
- `*** Keywords ***` — `<Service> Open Connection` / `<Service> Close
  Connection` helpers, then one typed keyword per RPC

All RPC keyword names are **prefixed with the service name** so two
services with same-named methods don't collide, and `${conn_name}` is
the first positional argument of every keyword so one test suite can
target multiple deployments.

## Exit codes

- `0` — at least one file written (or stdout dumped) successfully
- `1` — generation failed (bad proto, no .proto files in folder,
  protoc rejected the sources, …) — error printed to stderr
- `1` — every file already existed and `--force` wasn't passed (nothing
  written; ambiguous "nothing to do" reported on stderr)

## CI / one-shot use

The tool is the **recommended path for CI**.  Unlike `mb-scaffold`, it
needs no bridge process — just `grpcio-tools` on the PYTHONPATH.  A
typical CI step:

```cmd
python -m MicroserviceBase.tools.robot_gen ^
    --proto-dir .\proto --out .\tests\resources --force
robot --test "*Smoke*" .\tests\
```

## GUI equivalent

The Manager GUI has a green **🟢 Generate Robot resources** button in
the methods panel of every connected gRPC service.  Clicking it opens
two native folder pickers (proto folder, output folder) and writes the
same files via the bridge's `POST /api/scaffold/robot` endpoint.  See
the long-form doc linked at the top of this section for the full
walk-through.
