# Contracts

The `.proto` files here are what the Python runtime (`python/`) and the C++
runtime (`cpp/`) both implement. Neither runtime runs `protoc` for them: the
Python one builds the descriptor in code, the C++ one writes the wire format
by hand. These files are the reference both are checked against, and what
a service written in another language compiles.

| File | Python | C++ | Checked by |
|---|---|---|---|
| `microservicebase/gui/v1/service_gui.proto` | `runtime/gui_proto.py`, `runtime/gui_server.py` | `runtime/src/ServiceGui.cpp` | `pytest/Contracts/test_ServiceGuiContract.py` |

A change here is a change for both runtimes and for the Manager GUI's
bridge (microservice-gui repo), which calls these services.
