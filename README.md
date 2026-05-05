# Microservice Manager GUI

A Bootstrap-based desktop / web app that wraps the FastAPI bridge with
a friendly UX for **operating** the runtime (start/stop Consul + Nomad,
inspect services, submit jobs) and **building** new ones (the Service
Creator wizard, equivalent to `mb-scaffold`).

> ↑ Repo root: [`../../`](../..) — framework architecture lives in
> [`../../docs/`](../../docs).

## What you can do here

| Task | Where |
|---|---|
| Start / stop Consul + Nomad agents, inspect cluster state, submit jobs | **Service Network** mode → see [Operating Consul + Nomad](docs/md/ops_consul_nomad.md) |
| Generate a new service scaffold (proto + domain + adapter + clients + Nomad HCL) | **Service Creator** mode → see [Service Creator wizard guide](docs/md/service_creator.md) |
| Inspect a running service, browse its gRPC methods, send test calls | **Services** mode (covered in the Operating doc above) |
| Use the in-app help (lighter, embedded inside the GUI itself) | Click the **?** in the navbar — renders `web/docs/help.html` |

## Two ways to launch

| Mode | Command | When |
|---|---|---|
| **Electron desktop** | `npm start` | Native window with system tray and bundled bridge auto-start |
| **Browser + Python bridge** | `python -m MicroserviceBase.adapters.ui_bridge.fastapi_bridge` then open `http://127.0.0.1:1112` | Headless boxes, shared sessions, existing Python env |

Both modes are fed by the same FastAPI bridge — what you do in one is
visible in the other.

## Documentation map

```
MicroserviceManagerGUI/
├── README.md / README.html         ← you are here
├── docs/                           ← long-form, GitHub-renderable
│   ├── md/   index.md   ops_consul_nomad.md   service_creator.md
│   ├── html/ index.html ops_consul_nomad.html service_creator.html
│   └── img/  (18 screenshots used by the docs above)
└── web/
    └── docs/
        ├── help.html               ← embedded in-app help (rendered
        │                             inside the running GUI when the
        │                             user clicks the ? button)
        └── img/  (10 screenshots)
```

The **long-form docs** in `docs/` are the canonical reference — they
render as standalone pages on GitHub, link out to the rest of the repo,
and cover material the in-app help skips (CLI equivalents, REST API,
troubleshooting depth).

The **in-app help** at `web/docs/help.html` is intentionally smaller —
it loads inside the running GUI so users don't have to context-switch
out to a browser tab. It links to the long-form docs for anything
beyond a quick lookup.

## Documentation entry points

- **[Doc index](docs/md/index.md)** — landing page with all GUI guides
- **[Operating Consul + Nomad](docs/md/ops_consul_nomad.md)** — Service
  Network tab, agent lifecycle, jobs / nodes / services dashboards,
  REST API equivalents
- **[Service Creator wizard](docs/md/service_creator.md)** — the 4-step
  scaffold-generation wizard, with screenshots of each step
- **HTML twins** — every `.md` has a `.html` sibling under `docs/html/`
  with sidebar nav, copy-to-clipboard buttons, and active-section
  highlighting

## Source layout

| Path | What |
|---|---|
| `web/` | Browser-renderable assets (HTML / CSS / JS) — works in Electron and as a static site served by the bridge |
| `web/index.html` | Main shell (mode toggle, navbar, panels) |
| `web/js/` | App scripts — `app.js`, `GrpcClient.js`, `ConsulDashboard.js`, `NomadDashboard.js`, `ServiceCreator.js`, etc. |
| `web/services/` | Per-service GUI plugins loaded dynamically |
| `web/docs/help.html` | Embedded in-app help |
| `electron/` | Electron wrapper (preload, IPC) |
| `dist/` | Built Electron output (gitignored) |
| `build.bat` / `build.sh` | Bundle scripts |

## Architecture

The GUI is a thin client over the FastAPI bridge at
`http://127.0.0.1:1112`. Every action in the UI maps to a bridge HTTP
endpoint — see the **CLI equivalents** table at the bottom of
[`docs/md/ops_consul_nomad.md`](docs/md/ops_consul_nomad.md) for the
full list.

```
┌─────────────────┐  HTTP/JSON   ┌──────────────────────┐  gRPC + Consul HTTP
│  Manager GUI    │  ─────────→  │  FastAPI bridge      │  ────────────────────→ Services
│  (Electron/web) │              │  (Python; in-process │                         (Consul-registered)
│                 │              │   reflect_client +   │  ──→ Consul HTTP API
│                 │              │   subprocess agents) │  ──→ Nomad HTTP API
└─────────────────┘              └──────────────────────┘
```
