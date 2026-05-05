# Manager GUI documentation

> 📄 *Also available as HTML:* [`../html/index.html`](../html/index.html)

Companion docs to the Microservice Manager GUI. The GUI itself is a
thin client over the FastAPI bridge — these docs explain what the
panels do, how they map to bridge endpoints, and how to script the
same operations from a terminal.

For a one-page overview of the GUI as a whole, start at
[`../../README.md`](../../README.md).

## Guides

### [Operating Consul + Nomad](ops_consul_nomad.md)

How the **Service Network** mode replaces the per-terminal
`consul agent -dev` / `nomad agent -dev` workflow:

- Bridge LED and what each colour means
- Consul tab: Setup form (Dev / Config / Connect) + Connected dashboard
- Nomad tab: same pattern + jobs table + Submit Job dialog
- Navbar infra status pills (live LEDs, click-to-jump)
- Typical end-to-end workflow (open GUI → service running)
- CLI equivalents — every GUI action mapped to its bridge HTTP endpoint
- Troubleshooting (port conflicts, stale PID files, missing services)

8 screenshots showing each state of the panels.

### [Service Creator wizard](service_creator.md)

The 4-step wizard for generating new service scaffolds (proto + domain
+ adapter + clients + Nomad HCL) without writing boilerplate:

- Step 1 — Basic Info (name, language, GUI type)
- Step 2 — Technology (server / client toolchain matrix)
- Step 3 — Methods (manual entry + import .proto)
- Step 4 — Review & Generate (output preview)
- What gets generated, where, and how to build it
- The `mb-scaffold` CLI equivalent + YAML config schema

10 screenshots covering each step + the generated file tree.

## Cross-references

| When you need… | Go to |
|---|---|
| The actual framework architecture (hexagonal layers, runtime model) | [`../../../../docs/`](../../docs/) (repo-level) |
| A toolchain setup guide (MSYS2, Qt6::Grpc, vcpkg + Qt MinGW) | [`../../../../../examples/docs/md/index.md`](../../../../examples/docs/md/index.md) |
| The lighter in-app help (loaded inside the running GUI) | `../../web/docs/help.html` (or click the **?** in the navbar when the GUI is running) |
| A worked example of a multi-service C++ project | [`../../../../examples/PowerDeviceService/README.md`](../../../../examples/PowerDeviceService/README.md) |

## In-app help vs long-form docs

| | In-app `web/docs/help.html` | Long-form `docs/` (this folder) |
|---|---|---|
| **Audience** | User running the app right now | Developer learning the framework |
| **Reading context** | Side panel inside the running GUI | GitHub / IDE markdown preview / browser |
| **Length** | Quick lookup (~500 lines) | Comprehensive (~1000-2000 lines per topic) |
| **Cross-links** | Mostly self-contained | Links across the repo (toolchains, examples, runtime) |
| **Screenshots** | 10 (one per major panel) | 18 (each panel state, plus per-wizard-step) |
| **Source of truth** | Mirror of long-form for the topics it covers | ✓ Canonical |

When the two diverge, fix the long-form first, then propagate the
relevant snippet into `help.html`.
