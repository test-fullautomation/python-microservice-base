# QML Shell Lifecycle — Sequence Diagrams

## Overview

The QML Shell is a shared Qt WASM binary that loads service `.qml` files at runtime.
This document indexes all lifecycle sequence diagrams (PlantUML `.puml` files).

## Diagrams

| # | Diagram | File | Description |
|---|---------|------|-------------|
| 1 | First-Time Shell Init + QML Load | [`sequence_qml_shell_first_load.puml`](sequence_qml_shell_first_load.puml) | Full flow from user click through shell bootstrap, factory init, canvas creation, XHR fetch of QML source, and `setData()` loading |
| 2 | Service API Call + Response | [`sequence_qml_service_call.puml`](sequence_qml_service_call.puml) | QML → C++ `EM_ASM` → JS bridge → RabbitMQ → response routing back via `_qtshell_onResponse` |
| 3 | Service Switching (Reuse Shell) | [`sequence_qml_shell_switch.puml`](sequence_qml_shell_switch.puml) | Canvas reparenting, `clearQml()` destroying old items, loading new service QML without re-downloading WASM |
| 4 | Cleanup | [`sequence_qml_shell_cleanup.puml`](sequence_qml_shell_cleanup.puml) | `clear()` teardown with `deleteLater()` and scene removal |
| 5 | String Marshaling (JS ↔ C++) | [`sequence_qml_string_marshaling.puml`](sequence_qml_string_marshaling.puml) | The `_allocUTF8` / `_qtshell_malloc` / `_qtshell_free` pattern for all JS→C++ string passing |

## Component Map

| Layer | Component | File | Role |
|-------|-----------|------|------|
| **JS** | app.js | `web/js/app.js` | Tier detection, service content routing |
| **JS** | QtShellManager | `web/js/QtShellManager.js` | Shell lifecycle, JS↔C++ bridge, response routing |
| **JS** | ServiceClient | `web/js/ServiceClient.js` | RabbitMQ request/response (Electron or FastAPI) |
| **C++** | main.cpp exports | `src/main.cpp` | `EMSCRIPTEN_KEEPALIVE` C functions: load/clear/callback |
| **C++** | ShellController | `src/ShellController.cpp` | Dynamic QML loading via `QQmlComponent::setData()` |
| **C++** | ServiceBridge | `src/ServiceBridge.cpp` | QML↔JS bridge: `callService()` + response signals |
| **QML** | main.qml | `src/main.qml` | Shell root window + `shellContainer` |
| **QML** | ServiceUI.qml | per-service | Service-specific UI, uses `ServiceBridge` context property |
