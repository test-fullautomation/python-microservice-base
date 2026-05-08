# Legacy framework docs — kept for reference

> **⚠️ These docs describe the older RabbitMQ + ServiceRegistry +
> ProcessHub runtime that has been replaced by gRPC + Consul + Nomad.**
> Don't follow them for new work.

## What's here

| File | Status | Modern replacement |
|---|---|---|
| `CONCEPT.md` | Pre-migration architecture overview (RabbitMQ, alias routing, Fleet, ProcessHub) | [`../concepts.md`](../concepts.md) + [`../architecture.md`](../architecture.md) |
| `troubleshooting-guide.md` | 23 symptoms keyed to RabbitMQ/ServiceRegistry/ProcessHub | [`../troubleshooting.md`](../troubleshooting.md) |

## Why kept

- Some architectural ideas (hexagonal layers, convention-over-config,
  zero-dependency domain) survived intact and the old write-up
  explains them well — useful background reading.
- ADRs in `../adr/` reference these documents; the references still
  resolve.
- Anyone maintaining a downstream fork that hasn't migrated yet still
  needs the original troubleshooting guide.

When the modern docs reach feature parity for diagnostics, the
troubleshooting-guide.md content will be retired entirely.
