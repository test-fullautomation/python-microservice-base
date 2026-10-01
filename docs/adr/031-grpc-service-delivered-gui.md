# ADR-031: Service-Delivered GUI over gRPC (`ServiceGui`)

## Status

Accepted

## Date

2026-09-24

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-09-24 | 1.0 | Initial version |
| 2026-09-24 | 1.1 | `ServiceGui` is not advertised through reflection |
| 2026-09-24 | 1.2 | Client retries a failed download; updates folders it fetched |

## Context

ADR-019 established that a service delivers its own GUI: the Manager GUI
asks the service for a ZIP of its GUI folder, extracts it under
`web/services/<folder>/` and renders it. That mechanism is carried by the
AMQP-era `svc_api_get_gui_checksum` / `svc_api_get_gui_files` calls on
`ServiceBase`.

Services have since moved to gRPC and Consul (ADR-028), and those services
have no such call. The Manager GUI's Consul path therefore reads
`web/services/<Meta.gui>/` from disk and nothing else: when the folder is
absent the service is shown with *"No GUI files were found"*, and somebody
has to copy files onto the operator's machine by hand. A fresh machine
cannot render a bench it is otherwise perfectly able to talk to.

The gap is visible in practice: deleting a component folder leaves a
running, healthy service with no screen until the folder is restored.

## Decision

Extend service-delivered GUIs to gRPC with a small contract every service
serves automatically.

```proto
package microservicebase.gui.v1;

service ServiceGui {
  rpc GetGuiInfo  (GuiInfoRequest)  returns (GuiInfo);
  rpc GetGuiFiles (GuiFilesRequest) returns (stream GuiChunk);
}
```

- **`GetGuiInfo`** answers `{folder, checksum, size_bytes, file_count,
  available}`. The folder is what Consul's `Meta.gui` names; the checksum
  is the client's cache key.
- **`GetGuiFiles`** streams the folder as a ZIP in 256 KiB chunks. A
  caller that sends a `known_checksum` that is still current gets one
  `unchanged` message and no bytes.

### Types without `protoc`

The contract is built from a `FileDescriptorProto` in
`runtime/gui_proto.py`, the way `adapters/signals/signal_proto.py` already
does. Services need no generation step, and both ends share one
descriptor, so they cannot drift.

### Service side

`ServiceRunner` binds the handlers itself when the service declares a GUI
(`settings.gui`) and a folder is found — `gui_dir`, else `gui/<gui>`,
`ui/<gui>`, `GUIs/<gui>` or `<gui>` beside the entry module. The scaffold's
`ui/<Service><version>/` layout is matched, so a generated service serves
its component with no extra code.

`ServiceGui` is served but **not advertised through reflection**. Its
types live in a private descriptor pool, so reflection could list the
service but not describe it — and a client that walks the list, like the
GUI's actions view, fails on the first entry it cannot describe. The
bridge calls it by method path and needs no reflection; hiding it also
keeps plumbing out of a service's public API, as ADR-017 did for the
`svc_api_get_gui_*` calls.

### Bridge side

`POST /api/service-gui/fetch/{service}` resolves the instance through
Consul, compares checksums, downloads, and then either extracts into
`web/services/<folder>/` (browser host, where the bridge serves `web/`) or
returns the ZIP for the desktop app to unpack through its preload — only
Electron knows whether it runs from the source tree or `%APPDATA%`.
`GET /api/service-gui/info/{service}` answers without downloading.

### Client side

Before the Consul path mounts anything — component or classic panel — it
brings the folder up to date from the service:

- **Folder missing or empty:** download it. A failed attempt is remembered
  for 15 seconds only, so a service that starts serving its files later is
  picked up without reloading the window.
- **Folder present and it came from the service** (a checksum is stored in
  `localStorage`): ask once per window whether the service's copy changed,
  and replace it if so. A failure here is silent; the files on disk still
  work.
- **Folder present but put there by hand** (no checksum): left alone, so
  local edits are never overwritten.

A missing folder never sends a stored checksum, or the bridge would answer
"unchanged" and write nothing.

## Consequences

### Positive

- A machine with an empty `web/services/` populates itself from whatever is
  running — no manual copying, no packaging step for the operator.
- Panels stay with the service they belong to, versioned in that service's
  repository.
- Updating a service's screen is a service deployment; the checksum makes
  the GUI pick it up on the next open.
- Streaming carries multi-megabyte packages (Qt WASM builds) that a single
  message could not, and the ZIP goes over the wire as bytes rather than
  base64 — the ~33 % overhead of ADR-019 is gone except on the desktop
  hand-off.

### Negative

- Services that are not built on `ServiceRunner` (other languages, the C++
  runtime, third-party services) do not serve the contract; the GUI falls
  back to the local folder and says so. Their panels still need shipping by
  other means.
- A service now reads its GUI folder at request time; a service that is
  deployed without its files answers `available: false` rather than failing
  loudly.
- The bridge writes into `web/services/`, so that directory must be
  writable; `MB_GUI_SERVICES_DIR` overrides it where it is not.

### Neutral

- The AMQP mechanism of ADR-019 stays as it is for registry services;
  nothing was removed.
- Extraction refuses any archive member or folder name that would escape
  the target folder, and caps a package at 64 MB.
- An update overwrites files in place; a file the service dropped from its
  folder stays on disk until the folder is deleted.

## References

- Contract: `MicroserviceBase/runtime/gui_proto.py`
- Service side: `MicroserviceBase/runtime/gui_server.py`, `runtime/server.py`
- Bridge side: `MicroserviceBase/adapters/ui_bridge/service_gui.py`
- Client side: `MicroserviceManagerGUI/web/js/app.js` (`_fetchGuiFromService`)
- Tests: `pytest/UIBridge/test_ServiceGui.py`
- Extends: ADR-019 (Service-Delivered GUI Plugin Architecture)
- Related: ADR-005 (Dual-Host GUI), ADR-028 (gRPC reflection as primary RPC)
