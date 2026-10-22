# configuration-gui

Testbench configuration in the Endoskeleton-based Manager GUI. Everything of
the feature lives in this folder, except the small hooks into the shell
(`INTEGRATION.patch`: `web/index.html` and `web/js/app.js`).

The GUI talks to the **Catalog service** and the **Configuration Hub** only
(gRPC through the bridge's `/api/grpc/call`). It has no device-specific
code: devices, their static config and their settings form come from the
catalog entry (`adapter`, `static_config`, `user_config_schema`).

| File | Role |
|---|---|
| `js/SchemaForm.js` | JSON Schema → fields, defaults, validation (type, default, enum, min/max, exclusive bounds, required, description, minLength/maxLength/pattern). DOM-free. |
| `js/ConfigCommon.js` | Shared utility functions (DOM helpers, banners, confirmLeave, version dropdown, emitter). |
| `js/ConfigBaseView.js` | Base view class providing shared sidebar navigation, search dropdown, inline create, version bar, error summary, and lifecycle for both Testbench and Infrastructure. |
| `js/TestbenchStore.js` | Workflow and state: list, open (`NOT_FOUND` = "not created yet"), devices, validation, save (Create vs Update), versions, retry. DOM-free. |
| `js/TestbenchView.js` | The "Testbenches" view (inherits from ConfigBaseView; device editing, SchemaForm, picker). |
| `js/InfraStore.js` | Infrastructure workflow and state: independent list, defaults v0, node placement (`node`, `datacenters`), validation, save via `UpdateConfiguration`, versions, retry. DOM-free. |
| `js/InfraView.js` | The "Infrastructure" view (infra sidebar pane with searchable dropdown input `#infraSearchInput` + `.infra-dropdown-menu`, list, and node placement editor). |
| `js/TestbenchConfig.js` | Coordinator for the shared sidebar `#testbenchSidebar` (sub-tabs `[Testbenches]` and `[Infrastructure]`), active view synchronization, and live count badges. |
| `css/testbench.css` | Styles (Bench theme tokens, shared sidebar switcher, dropdown menu, editor cross-nav tabs). |
| `catalog_device_mock/device_catalog.json` | **Temporary** catalog data (no Catalog service yet). The client reads it instead of the Catalog service; the format is the sidecar-aggregate `{version, entries[]}`. Set `localStorage.mm_catalog_mock = '0'` to use the real service again, then delete this folder. |
| `js/HubMock.js` | **Temporary** in-memory Configuration Hub (UI-only mode), persisted in `localStorage.mm_hub_mock_data`. Same semantics as the hub: versions, `NOT_FOUND`, `ALREADY_EXISTS`, provider default for infrastructure, `INVALID_ARGUMENT`. On by default; `localStorage.mm_hub_mock = '0'` uses the real Hub, then delete this file. |
| `test/test_testbench.js` | Node tests: `cd web/configuration-gui && node test/test_testbench.js` (116 tests covering schema, stores, hubs, mocks). |
| `test/harness.html` | Demo with an in-memory Catalog + Hub: `cd web && python3 -m http.server 8099`, open `/configuration-gui/test/harness.html` (`?catalog=down`, `?hub=down` show outages). |

## Behaviour

- **Single Ribbon Button & Shared Sidebar**: A single ribbon button (`#btnModeTestbench`) and footer switch activate the shared Configuration view. The sidebar `#testbenchSidebar` contains sub-tabs for switching between `[Testbenches]` and `[Infrastructure]` with live count badges, while maintaining clean separation of concerns.
- **Editor Cross-Navigation**: When editing any testbench, top tabs `[Testbench Devices]` and `[Infrastructure Placement]` allow one-click switching between device configuration and node placement for the same testbench ID.
- **List**: `ListConfigurations("testbench")`, empty state, create (id + name), latest version shown. Opening an unknown id is "not created yet", not an error.
- **Add device**: choose a model from `ListDeviceModels`; `GetDeviceModel` provides the read-only `static_config` and the settings schema. New devices are pre-filled with schema defaults. `device_id` must be non-empty and unique in the testbench.
- **Validation**: client side against the schema; the field and reason are shown and Save is disabled while anything is invalid. Saved devices that were not edited are never re-validated (a changed catalog does not reject them).
- **Save**: payload `{id, name, devices[{device_id, catalog_ref, adapter, static_config, user_config}]}`; `CreateConfiguration` for a new testbench, `UpdateConfiguration` otherwise (new version). `deployment_descriptor` is never sent. Hub errors are shown; the input stays in memory after a failure.
- **Infrastructure configuration**: a completely independent document and lifecycle from testbench (keyed by testbench ID, own version, validation, and Save lifecycle).
  - **Searchable Dropdown in Shared Sidebar**: in the Infrastructure sub-pane of the shared sidebar, a search input `#infraSearchInput` and dropdown `.infra-dropdown-menu` search both stored infrastructure configurations and known testbenches from the Hub (offering default v0) or entering a new ID, alongside a quick-create toggle and list.
  - **Defaults and Save**: `GetConfiguration("infrastructure", id)`; on `NOT_FOUND`, `GetDefaultConfiguration` (version 0, node `client1`, datacenters `["dc1"]`, marked default). First save creates version 1 via `UpdateConfiguration`. Saving testbench and infrastructure are strictly isolated and never touch each other.
- **Versions**: `ListConfigurationVersions`; a previous version opens read-only.
- **Availability**: a Catalog failure never blocks viewing a saved testbench; the banner names the failed service and offers Retry.
- **Catalog changes**: `GetCatalogVersion` is read when a device form opens; the last version seen at save is remembered per testbench in `localStorage` and a non-blocking notice shows when it differs.

## Configuration

Consul service names default to `catalog` and `configuration_hub`; override
with `localStorage` keys `mm_catalog_service` and `mm_confighub_service`.
Infrastructure documents are saved as `{id, node, datacenters}`.
