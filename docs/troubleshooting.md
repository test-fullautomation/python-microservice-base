# Troubleshooting

> 📄 *Also available as HTML:* [`troubleshooting.html`](troubleshooting.html)

Symptom-indexed problems and fixes for the current
gRPC + Consul + Nomad stack. For pre-migration symptoms (RabbitMQ,
ServiceRegistry, ProcessHub, Fleet hubs), see
[`_legacy/troubleshooting-guide.md`](_legacy/troubleshooting-guide.md).

> **How to use:** `Ctrl+F` for the symptom you're seeing, or browse
> by category. Each entry says what it usually means and what to do.

## Quick index

| Symptom | Section |
|---|---|
| Manager GUI bridge LED stays red after `npm start` | [Bridge](#bridge) |
| Service appears in Consul UI but not in the GUI sidebar | [Service discovery](#service-discovery) |
| Service registers, then disappears from Consul a few seconds later | [Service discovery](#service-discovery) |
| GUI shows "Reflection RPC … failed: UNIMPLEMENTED" | [gRPC](#grpc) |
| GUI shows "Reflection unavailable … no .proto files matched" | [gRPC](#grpc) |
| Nomad job stays "pending" forever | [Nomad](#nomad) |
| `nomad job run` succeeds but service never starts | [Nomad](#nomad) |
| `consul agent -dev` won't start ("port 8500 in use") | [Consul / Nomad agents](#consul--nomad-agents) |
| `vcpkg install grpc` fails with "corrupt patch" | [Build (vcpkg)](#build-vcpkg) |
| `vcpkg install grpc` fails with gcc 13.1.0 ICE on `per_cpu.h` | [Build (vcpkg)](#build-vcpkg) |
| Generated server returns `UNIMPLEMENTED` for reflection RPCs | [Build (vcpkg)](#build-vcpkg) |
| Built `.exe` won't run: `libprotobuf.dll not found` (or `Qt6Core.dll`) | [Build (Qt)](#build-qt) |
| Qt Creator can't find `gRPC` package | [Build (Qt)](#build-qt) |
| `import_prebuilt.bat` extracts but Qt Creator still fails | [Build (Qt)](#build-qt) |
| `mb-scaffold --help` works but generation fails | [Scaffold](#scaffold) |
| Generated service won't compile | [Scaffold](#scaffold) |

## Bridge

### Bridge LED stays red after `npm start` (Electron mode)

The FastAPI bridge process didn't start, usually because port 1112 is
already taken.

```cmd
netstat -ano | findstr :1112
```

If something else holds 1112: kill it, or set
`MB_BRIDGE_URL=http://127.0.0.1:<other-port>` in your environment
before launching the GUI.

### Bridge LED amber and never turns green

Bridge is starting / re-trying. Wait ~10s. If it stays amber:

- Look at the bridge log (Electron mode: dev tools console; web
  mode: terminal where you launched `python -m
  MicroserviceBase.adapters.ui_bridge.fastapi_bridge`).
- Common cause: missing Python dep — `pip install -e .` again.

### Bridge LED red in browser/web mode

The bridge **is** the web server in this mode. A red LED means you
lost the page (the Python process died). Re-launch the bridge and
refresh the page.

## Service discovery

### Service appears in Consul UI (`:8500/ui`) but not in the GUI sidebar

The GUI is connected to a different Consul cluster than the service
registered with.

- Check the navbar's connected-cluster chip — that's where the GUI
  is looking.
- Check the service's `CONSUL_ADDR` env var — that's where the
  service registered.
- Either fix the service's `CONSUL_ADDR` (in the `.nomad.hcl`
  `env` block) or click **Connect** in the navbar to add a chip for
  the right cluster.

### Service registers, then disappears from Consul after ~30 seconds

Consul's TCP health check is failing. Most common reasons:

- Service crashed silently — check Nomad logs:
  `nomad alloc logs <alloc-id>`
- Service didn't actually start gRPC — check that
  `<PREFIX>_GRPC_PORT` was set in the env (Nomad does this via
  `${NOMAD_PORT_grpc}`)
- Port mismatch — service registered with port X but listens on Y;
  audit the registration in `ServiceRunner` (or its C++ equivalent)

### GUI says "No services found" but Consul has services registered

Some services exist but none are passing health checks. The GUI
filters for `?passing=true`. To see all (including failing), open
the Consul UI directly via the **Open Consul UI** button in the
Service Network tab.

## gRPC

### "Reflection RPC … failed: UNIMPLEMENTED" when clicking a service

The server doesn't ship `grpc++_reflection`. Two paths:

**Quick:** The GUI now offers a proto-path input field below the
error. Type the folder containing the service's `.proto` files
(e.g. `D:\…\<project>\proto`) and click **Use this path**. The
bridge falls back to `LocalProtoClient` (compiles `.proto` from
disk).

**Permanent:** Rebuild the server with reflection enabled. For
vcpkg-built servers: this is now the default — re-run
`init_vcpkg_overlay.bat --upgrade` and rebuild grpc, then redeploy
the service. See [`changelog.md`](changelog.md) for what changed.

### "Reflection unavailable … no .proto files matched in search paths"

The GUI's fallback couldn't find any `.proto` files. Either:

- Set `MB_PROTO_SEARCH_PATH` env var (semicolon-separated
  directories) before launching the bridge, or
- Type the path into the GUI's proto-path input field and click
  **Use this path** (persisted per-service in `sessionStorage` for
  the rest of the browser session)

### gRPC call returns `UNAVAILABLE: failed to connect to all addresses`

The address Consul returned isn't reachable from where the client
runs:

- Check that the service is on the same machine / network as the
  caller (Consul advertises its `Address`; if it's a private IP,
  callers from outside that network can't reach it)
- For dev: set `bind_addr = 0.0.0.0` in Consul if you want services
  visible from other dev machines

### gRPC call returns `INVALID_ARGUMENT` immediately

Usually a JSON marshalling problem. The bridge's `call_method`
parses the JSON request into a dynamic protobuf — common mistakes:

- Field name typo (proto uses snake_case; check the request panel's
  pre-filled skeleton for the correct names)
- Type mismatch (e.g. sending a string for an `int32` field)
- Extra unknown fields — the dynamic builder is strict by default

## Nomad

### Job stays "pending" forever

`nomad node status` to confirm there's a healthy client. Then
`nomad job status <name>` and look at the placement failure
message. Most common in dev mode:

- Driver mismatch — generated jobs use `raw_exec`. Dev mode enables
  this automatically; if you're using a custom config, add the
  `raw_exec` plugin block.
- Memory / CPU limits in the job exceed what the dev-mode client
  reports.

### `nomad job run` succeeds but service never starts

Check `nomad alloc logs <alloc-id>` — the binary probably crashed
on startup. Common causes:

- Missing DLL (Windows): the `.hcl` runs the binary in-place; if
  you didn't `deploy_qt_vcpkg.bat` first, the runtime DLLs may not
  be on PATH. Either deploy first or use the deployed
  `dist-qt-vcpkg/run_<svc>.bat` wrapper which sets PATH.
- Wrong working directory: HCL has `command = "C:/path/to/run.bat"`;
  the .bat needs to be at that exact path. Run
  `prep_nomad_paths.bat` after moving a project.
- `CONSUL_ADDR` unreachable — check the `env` block in the HCL.

### Job ran fine, then I edited the HCL and `nomad job run` said "No changes"

Nomad re-evaluates only when `Job.Modify` actually changes. If you
edited an `env` value but not the version, force re-run:

```cmd
nomad job stop <name>
nomad job run deploy/<name>.nomad.hcl
```

## Consul / Nomad agents

### "Port 8500 is already in use" when starting Consul (or 4646 for Nomad)

Another agent is already running. Either:

- Use the GUI's Service Network → Consul / Nomad → **Connect to
  Existing** form to point at the running one
- Or stop the running one (`tasklist | findstr consul`,
  `taskkill /pid <pid>`) and click **Start Agent**

### "Agent already running (PID …)" but the LED is gray

Stale PID file from a crashed agent. Delete and retry:

```cmd
del %TEMP%\msbase_consul_agent.pid
del %TEMP%\msbase_nomad_agent.pid
```

Then click Start Agent in the GUI.

## Build (vcpkg)

### `vcpkg install grpc` fails with "corrupt patch at line 23"

Patch file `00018-gcc13-per-cpu-ice-workaround.patch` has zero-byte
blank lines (some editors strip trailing whitespace). Pull the
latest scaffold, or run `init_vcpkg_overlay.bat --reinit`. The
generator now uses a `{SP}` placeholder so blank context lines keep
their leading space.

### gcc 13.1.0 ICE in `per_cpu.h` during `vcpkg install grpc`

Patch `00018-gcc13-per-cpu-ice-workaround.patch` should have applied;
verify it's listed in `ports/grpc/portfile.cmake`'s `PATCHES`.
`init_vcpkg_overlay.bat --upgrade` will (idempotently) ensure it's
there.

### Generated server returns `UNIMPLEMENTED` for reflection (vcpkg path)

vcpkg's `gRPC_BUILD_CODEGEN` got dropped for the target triplet —
the overlay portfile must force it on. Run:

```cmd
init_vcpkg_overlay.bat --upgrade
del /q "%LOCALAPPDATA%\vcpkg\archives\??\grpc_*"
rmdir /s /q build-qt-vcpkg
build_qt_vcpkg.bat
```

Verify after rebuild:

```cmd
dir build-qt-vcpkg\vcpkg_installed\x64-mingw-qt\lib\libgrpc++_reflection.a
```

## Build (Qt)

### Built `.exe` complains `libprotobuf.dll not found` (or `Qt6Core.dll`)

Windows DLL search only looks at the `.exe`'s folder and `%PATH%`.
Three fixes (pick one):

- **F5 in Qt Creator**: Projects (Ctrl+5) → Run → Environment →
  Path → Edit, prepend (semicolon-separated):
  `<build-dir>\vcpkg_installed\x64-mingw-qt\bin;C:\Qt\6.x.y\mingw_64\bin;C:\Qt\Tools\mingw1310_64\bin`
- **Run from a deployed dist**: `deploy_qt_vcpkg.bat` (or
  `cd qt_client_grpcpp && deploy_qt.bat`) copies every DLL next to
  the `.exe` in `dist-qt-vcpkg/`. Self-contained.
- **System PATH**: prepend the three dirs to your user-level PATH —
  works for any new terminal / Qt Creator.

### Qt Creator: "Could not find a package configuration file provided by `gRPC`"

Qt Creator didn't pass `-DCMAKE_TOOLCHAIN_FILE` to the build. Either
use the bundled `vcpkg-x64-mingw-qt` CMake preset, or stay on the
kit and add these four entries to *Initial Configuration*:

```
CMAKE_TOOLCHAIN_FILE   = D:/Project/Out/vcpkg/scripts/buildsystems/vcpkg.cmake
VCPKG_TARGET_TRIPLET   = x64-mingw-qt
VCPKG_OVERLAY_TRIPLETS = D:/path/to/your/project/triplets
VCPKG_OVERLAY_PORTS    = D:/path/to/your/project/ports
```

(use absolute paths — Qt Creator doesn't expand `${sourceDir}` in
Initial Configuration; var name is **plural** TRIPLETS with S.)

Then *Build → Clear CMake Configuration → Run CMake*.

### `import_prebuilt.bat` extracts but Qt Creator still fails to find gRPC

The prebuilt zip went into one build dir, but Qt Creator is using a
different one. Verify:

```cmd
dir build\Desktop_Qt_*\vcpkg_installed\x64-mingw-qt\share\grpc\
```

If empty, check the import script's output for which build dirs it
detected. Add `VCPKG_MANIFEST_INSTALL = OFF` (Boolean) to Qt
Creator's Initial Configuration so vcpkg doesn't try to overwrite
the imported tree.

## Scaffold

### `mb-scaffold` works but generation fails with "bridge not reachable"

The CLI POSTs to `http://127.0.0.1:1112/api/scaffold/generate-v2`.
That bridge has to be running:

```cmd
python -m MicroserviceBase.adapters.ui_bridge.fastapi_bridge
```

(or launch the Electron Manager GUI, which auto-starts the bridge).
Override the URL with `--bridge-url` or `MB_BRIDGE_URL`.

### Generated service won't compile

Most likely: missing toolchain. Match the `--client-grpc` /
`--server-grpc` you scaffolded with the toolchain you have:

- `--server-grpc msys2`: needs MSYS2 + `mingw-w64-x86_64-grpc`
  installed. See [`../examples/docs/md/mingw_setup.md`](../examples/docs/md/mingw_setup.md).
- `--server-grpc vcpkg`: needs vcpkg checkout + Qt installer's
  MinGW. See [`../examples/docs/md/vcpkg_setup.md`](../examples/docs/md/vcpkg_setup.md).
- `--gui qt`: needs Qt 6.8+ with the GRPC + Protobuf modules. See
  [`../examples/docs/md/qt_grpc_setup.md`](../examples/docs/md/qt_grpc_setup.md).

After the toolchain is set up:

```cmd
cd <generated_service>
build_deploy_msys2.bat        # or build_qt_vcpkg.bat for vcpkg
```

## See also

- [`architecture.md`](architecture.md) / [`runtime_model.md`](runtime_model.md) — to understand why a symptom happens
- [`../examples/docs/md/index.md`](../examples/docs/md/index.md) — toolchain setup for build problems
- [`../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md`](../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md) — Consul/Nomad GUI ops + their own troubleshooting tail
- [`_legacy/troubleshooting-guide.md`](_legacy/troubleshooting-guide.md) — pre-migration symptoms (RabbitMQ, ProcessHub, Fleet)
