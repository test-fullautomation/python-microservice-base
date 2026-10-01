# charts

Live signal charts for the bench.

- **Tile kind `signal-strip`:** one sparkline per signal over a sliding
  window. Fields: `signals` (1-8 signal names), `window` (`"120s"`,
  `"5m"`; default 60 s), optional `min`, `max`, `digits`. The component
  using it must declare `signals.subscribe`.
- **Drawer tab "Chart":** plots the signals of the tile selected on the
  bench (its `signal` fields, or a `signal-strip`'s signals).

Needs live signals (the bridge's `/api/signals/stream` and a reachable
`signal-discovery`). Redraws at most 10 times a second; while the bench is
hidden it holds no subscription, timer or animation frame.

```json
{ "id": "trend", "size": "2x1", "kind": "signal-strip", "title": "Chamber",
  "signals": ["bench.chamber.temp.degC", "bench.chamber.setpoint.degC"], "window": "120s" }
```
