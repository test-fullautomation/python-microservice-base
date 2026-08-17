# Diagrams

Every diagram below is rendered at build time from the `.puml` sources in
[`docs/diagrams/`](https://github.com/test-fullautomation/python-microservice-base/tree/develop/docs/diagrams).
The `.puml` files are the single source of truth — this page `!include`s
them rather than duplicating their content, so a diagram can never drift
from the page that shows it.

Click any diagram to open it full-screen (zoom and pan supported).

---

## System architecture

### Canonical architecture

The end-to-end picture: services, the gRPC substrate, Consul discovery,
Nomad orchestration, and the Manager GUI.

```plantuml
!include diagrams/00_canonical_architecture.puml
```

### Hexagonal layering

How `domain/`, `ports/` and `adapters/` relate — the dependency rule is
that arrows only ever point inward, toward the domain.

```plantuml
!include diagrams/hexagonal_architecture.puml
```

### Component view

```plantuml
!include diagrams/component.puml
```

---

## Class structure

### Domain

Pure business types with no infrastructure dependencies.

```plantuml
!include diagrams/class_domain.puml
```

### Ports

The interfaces the domain defines and the adapters implement.

```plantuml
!include diagrams/class_ports.puml
```

### Adapters

Concrete implementations — gRPC, Consul, Nomad, and the legacy AMQP path.

```plantuml
!include diagrams/class_adapters.puml
```

---

## Runtime sequences

### Service registration

What happens between process start and the service becoming discoverable.

```plantuml
!include diagrams/sequence_registration.puml
```

### RPC call

A unary call and a server-streaming call, end to end.

```plantuml
!include diagrams/sequence_rpc.puml
```

### Communication overview

```plantuml
!include diagrams/sequence_communication.puml
```

### Shutdown

Graceful deregistration and process teardown.

```plantuml
!include diagrams/sequence_shutdown.puml
```

### Process lifecycle states

```plantuml
!include diagrams/state_process_lifecycle.puml
```

---

## Manager GUI

### GUI architecture

```plantuml
!include diagrams/gui_architecture.puml
```

### GUI loading tiers

```plantuml
!include diagrams/flow_gui_loading_tiers.puml
```

### Service plugin loading

```plantuml
!include diagrams/sequence_gui_plugin_loading.puml
```

### Qt UI loading flow

```plantuml
!include diagrams/component_flow_qt_ui_loading.puml
```

### QML / WASM loading

```plantuml
!include diagrams/sequence_gui_qml_wasm_loading.puml
```

---

## Qt service templates

### Template families

```plantuml
!include diagrams/component_qt_service_templates.puml
```

### Widget template

```plantuml
!include diagrams/component_qt_template_widget.puml
```

### QML template

```plantuml
!include diagrams/component_qt_template_qml.puml
```

### WASM template

```plantuml
!include diagrams/component_qt_template_wasm.puml
```

---

## QML shell internals

### First load

```plantuml
!include diagrams/sequence_qml_shell_first_load.puml
```

### Switching services

```plantuml
!include diagrams/sequence_qml_shell_switch.puml
```

### Cleanup

```plantuml
!include diagrams/sequence_qml_shell_cleanup.puml
```

### Service call from QML

```plantuml
!include diagrams/sequence_qml_service_call.puml
```

### String marshaling

```plantuml
!include diagrams/sequence_qml_string_marshaling.puml
```

---

!!! note "Superseded diagrams"
    Broker-era diagrams (alias routing, fleet connect/disconnect, realtime
    update exchange) live in `docs/diagrams/_archive/`. They document the
    pre-migration RabbitMQ architecture and are kept for historical
    reference only — see [ADR-028](../adr/028-grpc-reflection-primary-rpc.md)
    for why gRPC replaced them.
