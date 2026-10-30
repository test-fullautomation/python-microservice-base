# microservice-gui-bridge

The Manager GUI's bridge: the FastAPI server between the GUI and the
services. It holds what only the GUI uses:

| Package | What |
|---|---|
| `microservice_gui_bridge.adapters.ui_bridge` | the FastAPI bridge, compositions, signal routes, service GUI download |
| `microservice_gui_bridge.adapters.local_hub` | the local process hub (start/stop processes from `hub_processes.json`) |
| `microservice_gui_bridge.adapters.nomad_hub` | the Nomad client and hub adapter |
| `microservice_gui_bridge.adapters.test_project` | test projects: Robot Framework and Temporal runners, runs, debugging |
| `microservice_gui_bridge.ports` | the hub manager and test project ports |

It builds on MicroserviceBase 3.x (registry, gRPC reflection client,
scaffold, signals, the ServiceGui contract). Services depend on
MicroserviceBase only, never on this package.

## Run

The GUI starts the bridge through `python/launcher.py`. By hand:

```
pip install MicroserviceBase ./bridge
python python/launcher.py --bridge-port 1112
```

From a checkout the bridge serves the GUI's `web/` folder; elsewhere set
`DASGUI_GUI_DIR` to the GUI folder.

## Test

```
cd bridge
python -m pytest tests
```

During development against a MicroserviceBase checkout,
`pip install -e <base checkout>` and `pip install --no-deps -e bridge`.
