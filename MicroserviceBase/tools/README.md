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
