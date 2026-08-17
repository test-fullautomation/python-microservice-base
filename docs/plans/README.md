# Plans

Forward-looking design documents that inform later ADRs and
implementation work.

> Each plan now has a **Status** banner at the top — read that first to
> know whether the plan is still load-bearing.

| Plan | Status | What it covers |
|---|---|---|
| [`gui-loading-flow.md`](gui-loading-flow.md) | ✅ Active | Multi-tier GUI detection waterfall (`gui_schema.json` / QML / `.wasm` / HTML / API explorer) used by `MicroserviceManagerGUI/web/js/app.js` |
| [`schema-driven-ui-builder.md`](schema-driven-ui-builder.md) | ✅ Active | Foundational plan for [ADR-021](../adr/021-schema-driven-ui-builder.md). Schema-driven tier emits Bootstrap UI from a `gui_schema.json` |
| [`qml-shell-cpp-infrastructure.md`](qml-shell-cpp-infrastructure.md) | ⚠️ Obsolete | Pre-gRPC migration design (RabbitMQ-era). The QML shell concept is still on the roadmap but needs a fresh design against the current runtime |

## See also

- [`../adr/`](../adr/README.md) — Architecture Decision Records (each
  references the plan(s) it built on)
- [`../changelog.md`](../reference/changelog.md) — what the gRPC + Consul + Nomad
  migration invalidated and what survived
- [`../architecture.md`](../architecture/overview.md) — current shape
