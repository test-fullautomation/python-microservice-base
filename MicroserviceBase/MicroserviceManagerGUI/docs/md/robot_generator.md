# Generate Robot Framework resources from a `.proto` folder

The Manager GUI and the bundled CLI can both turn a folder of `.proto`
files into a set of **typed Robot Framework keyword libraries** —
one `.resource` per service, one keyword per RPC method. The keywords
wrap [`QConnectBase.ConnectionManager`](https://github.com/test-fullautomation/robotframework-qconnect-base)
so test authors don't have to hand-roll JSON `send_cmd` strings.

This page covers what the generator produces, how to invoke it from
both UIs, and the runtime conventions the generated keywords follow.

## What you get

For every `service` declared anywhere under your `.proto` folder, the
generator emits `<snake_service_name>.resource` with:

| Section | Contents |
|---|---|
| `*** Settings ***` | `Library QConnectBase.ConnectionManager` + a `Library Collections`. Library is loaded as `conn_manager` (alias) so multi-connection tests can talk to many services without name clashes. |
| `*** Variables ***` | One per-service `${<SERVICE>_FQN}` constant carrying the fully-qualified proto service name (e.g. `Com_Setup_Device.ComSetupDeviceService`). |
| `*** Keywords ***` | A `<Service> Open Connection` / `<Service> Close Connection` helper pair, then one typed keyword per RPC. All keyword names are **prefixed with the service name** so two services with same-named methods (`Connect`, `Reset`, …) don't collide. |

### Keyword conventions

| Convention | Why |
|---|---|
| **Prefixed names** — `<Service> <Method>` e.g. `Com Setup Device Service Set Interface Type` | Two services with same-named methods can co-exist in one test suite. |
| **`${conn_name}` is the first positional argument** of every keyword | Lets one test open N connections to different deployments (e.g. `set` vs `read`) and target each call explicitly. |
| **`Open Connection` / `Close Connection`** helpers (not `Connect` / `Disconnect`) | Proto services frequently declare RPCs *named* `Connect()` / `Disconnect()`. Helper names that shadow those would collide with the generated RPC keyword. The "Open/Close Connection" spelling is unambiguous. |
| Single-space-only keyword names | Robot's parser treats 2+ consecutive spaces as a delimiter — names with double spaces get truncated. The converter dedupes underscores at camelCase boundaries (`GetSubDeviceType_ListCount` → `Get Sub Device Type List Count`, never `…Type  List…`). |
| **No-arg RPCs skip the args-dict scaffolding** | Methods with `Empty` request messages render as a single `verify` call with a constant `send_cmd` literal — no `Create Dictionary`, no `Evaluate json.dumps`. Cleaner output for a common case. |
| Server-streaming methods use a dedicated template | Doc-string warns that the response is buffered into a list (`conn_manager.verify` is one round-trip); for incremental delivery, point users at the lower-level `wait_4_trace` keyword. |

### Sample output

For a proto containing:

```proto
service ComSetupDeviceService {
  rpc SetInterfaceType(InterfaceTypeRequest) returns (CommandResponse);
  rpc GetInterfaceType(Empty)                returns (GetInterfaceTypeResponse);
  rpc Connect(Empty)                         returns (CommandResponse);
}
message InterfaceTypeRequest { int32 type = 1; }
message Empty {}
```

The generator emits `com_setup_device_service.resource`:

```robot
*** Settings ***
Library    QConnectBase.ConnectionManager    WITH NAME    conn_manager
Library    Collections

*** Variables ***
${COM_SETUP_DEVICE_SERVICE_FQN}    Com_Setup_Device.ComSetupDeviceService

*** Keywords ***
Com Setup Device Service Open Connection
    [Arguments]    ${conn_name}    ${target}=${EMPTY}    ${service_name}=${EMPTY}
    ...            ${consul_addr}=${EMPTY}    ${proto_dir}=${EMPTY}
    ...            ${timeout_seconds}=30.0
    &{conf}=    Create Dictionary    conn_type=GrpcClient
    ...                              target=${target}
    ...                              service_name=${service_name}
    ...                              consul_addr=${consul_addr}
    ...                              full_service_name=${COM_SETUP_DEVICE_SERVICE_FQN}
    ...                              proto_dir=${proto_dir}
    ...                              timeout_seconds=${timeout_seconds}
    conn_manager.connect    conn_name=${conn_name}    conn_conf=${conf}

Com Setup Device Service Close Connection
    [Arguments]    ${conn_name}
    conn_manager.disconnect    ${conn_name}

Com Setup Device Service Set Interface Type
    [Arguments]    ${conn_name}    ${type}
    &{args}=    Create Dictionary    type=${type}
    ${cmd}=     Evaluate    json.dumps({"method":"SetInterfaceType","args":${args}})    json
    ${res}=     conn_manager.verify    conn_name=${conn_name}    send_cmd=${cmd}
    RETURN      ${res}

Com Setup Device Service Get Interface Type
    [Arguments]    ${conn_name}
    ${res}=    conn_manager.verify    conn_name=${conn_name}    send_cmd={"method":"GetInterfaceType"}
    RETURN     ${res}

Com Setup Device Service Connect
    [Arguments]    ${conn_name}
    ${res}=    conn_manager.verify    conn_name=${conn_name}    send_cmd={"method":"Connect"}
    RETURN     ${res}
```

Note how `Connect` (the RPC keyword) and `Open Connection` (the helper)
co-exist without collision.

### Using the generated resource in a test

```robot
*** Settings ***
Resource    com_setup_device_service.resource

*** Test Cases ***
SetInterfaceType Smoke
    Com Setup Device Service Open Connection    conn=device
    ...    service_name=multi_proto
    ...    consul_addr=http://127.0.0.1:8500
    ...    proto_dir=${CURDIR}/../proto

    ${res}=    Com Setup Device Service Set Interface Type    conn=device    type=0
    Should Be Equal As Integers    ${res}[errorcode]    0

    [Teardown]    Com Setup Device Service Close Connection    device
```

The `proto_dir` argument is forwarded to QConnectBase's GrpcClient and
is only used when the server lacks gRPC reflection (typical for C++
services compiled without `grpc++_reflection`). When reflection works,
leave it empty.

## Triggering generation

### From the GUI (Manager → gRPC service panel)

1. Connect to your gRPC service in the Manager GUI (Service Network →
   click a registered service).
2. Once the methods panel renders, the **🟢 Generate Robot resources**
   button appears in the top-right of the methods list. It's there
   regardless of whether methods were discovered via reflection or by
   compiling a local `.proto` folder.
3. Click it:
   - If you've already provided a `.proto` folder (via the fallback
     card), it's used as the source.
   - Otherwise a native folder picker asks for the proto folder.
4. A second native folder picker asks for the output folder (defaults
   to a sibling `robot/` directory next to your `proto/` folder).
5. If existing `.resource` files would be overwritten, a confirm
   dialog asks before proceeding (cancel → skipped files reported as
   a warning toast, no destructive overwrite).
6. Success toast: *"Wrote N `.resource` file(s) to …"*.

The same button also appears at the bottom of the no-reflection
"Provide a `.proto` folder" fallback card — clicking it there uses
whichever path you just typed.

### From the CLI

```cmd
"C:\Program Files\RobotFramework\python3\python.exe" -m MicroserviceBase.tools.robot_gen ^
    --proto-dir D:\projects\TestService\proto ^
    --out       D:\projects\TestService\robot
```

Flags:

| Flag | Meaning |
|---|---|
| `--proto-dir DIR` (required) | Folder containing `*.proto` files (non-recursive — only top-level `.proto` files are scanned). |
| `--out DIR` | Folder to write `.resource` files into. Created if missing. Required unless `--stdout`. |
| `--service NAME` (repeatable) | Only emit resources for these services. Default = all. |
| `--force` | Overwrite existing `.resource` files in `--out`. Default = refuse + report skipped. |
| `--stdout` | Print every generated resource to stdout, separated by a comment header (useful for diffing or piping into a single file). |

The CLI does **not** require the bridge to be running — it calls the
generator in-process. This is the path CI pipelines should use.

### From the bridge HTTP API

```
POST /api/scaffold/robot
Content-Type: application/json

{
  "proto_dir": "D:/projects/TestService/proto",
  "out_dir":   "D:/projects/TestService/robot",
  "force":     false,
  "services":  []
}
```

- `out_dir` empty → response carries `{ files: { "<rel>": "<content>" } }`
  (caller persists them — used by the GUI button).
- `out_dir` non-empty → response carries `{ written: [...], skipped: [...] }`.
- `services` empty → all services. Non-empty → filter to the listed
  service names.

## How proto fields map to Robot keyword args

Each non-empty request message becomes one positional argument per
field. The proto scalar type is preserved as Robot's variable name
suffix is **not** type-annotated (Robot is dynamically typed) — but
the conversion at the wire layer is determined by the proto descriptor,
so passing strings where ints are expected fails at the gRPC layer.

| Proto field | Generated arg | Wire shape |
|---|---|---|
| `int32 channel = 1;` | `${channel}` | int |
| `bool enabled = 1;` | `${enabled}` | bool |
| `string parametername = 1;` | `${parametername}` | string |
| `repeated string tags = 1;` | `${tags}` | string (serialized as-is — caller should pass a JSON list, not a Robot list) |

Nested messages and enums in the request fall back to a `string`
signature on the keyword — the test author hand-builds the JSON for
those fields.

## Re-running the generator

Re-running is non-destructive by default — existing `.resource` files
are reported in the *skipped* list rather than overwritten. To force
a refresh:

- GUI: confirm the overwrite dialog that appears.
- CLI: pass `--force`.

Both paths only touch files whose names match the generated naming
convention; hand-authored `*.resource` files alongside generated ones
are untouched even with `--force`.

## Default-valued scalars (proto3 quirk — important)

Proto3 omits scalar fields holding their default value (0, false, "")
from the wire and from `MessageToDict` by default. Without an opt-in,
a successful unary RPC returning `{"errorcode": 0}` would surface as
`{}` in your test — `${res}[errorcode]` would raise a KeyError.

The bridge enables the opt-in (`always_print_fields_with_no_presence=True`,
or the deprecated `including_default_value_fields=True` on older
`protobuf` releases), so your tests can rely on every documented
scalar field being present in the returned dict.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Failed: Failed to fetch` | Bridge not reachable on the configured port. Restart the Manager GUI (it auto-spawns the bridge) or check the Bridge LED. |
| `Reflection unavailable … no .proto files matched in search paths` | Server doesn't ship reflection AND no proto folder is set. Click the "Provide a `.proto` folder" card and type the folder, OR set the `MB_PROTO_SEARCH_PATH` env var in the bridge environment. |
| `protoc returned exit code 1 for sources [<long list>]` | The fallback's auto-glob is picking up duplicate `google/protobuf/*.proto` from build directories. Set an **explicit** proto folder in the GUI — the generator uses *only* that folder when set, and prunes `build/`, `build-*`, `vcpkg_installed/`, `node_modules/`, `_legacy/`, `.git/`, `__pycache__/` subdirs from the scan. |
| `Keyword with same name defined multiple times` (Robot parse error) | Pre-`Open Connection` rename, or pre-underscore-dedupe — regenerate with a current build. The current generator guarantees no internal collisions for any well-formed proto. |
| Generated keyword's response dict is missing `errorcode`, `enabled`, etc. | The fix lives in the bridge (`always_print_fields_with_no_presence=True` on `MessageToDict`). If you're seeing stripped fields, you're running a stale bridge — restart it. |

## Where it lives in the codebase

| File | Role |
|---|---|
| `MicroserviceBase/adapters/scaffold/robot_tmpl.py` | Parser + emitter — public entry `generate_robot_resources(proto_dir)` |
| `MicroserviceBase/adapters/scaffold/templates/robot/*.tmpl` | The 4 template files used by the emitter |
| `MicroserviceBase/tools/robot_gen.py` | CLI wrapper |
| `MicroserviceBase/adapters/ui_bridge/fastapi_bridge.py` (`POST /api/scaffold/robot`) | HTTP endpoint used by the GUI |
| `MicroserviceBase/MicroserviceManagerGUI/web/js/app.js` (`_runRobotGen`) | GUI button click handler |
| `test/testfiles/MSB_0021.py` | Regression guard for emitter output shape (Connect/Disconnect helpers, prefix, conn_name-first, no-collision invariants) |
