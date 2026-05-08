# ADR-018: Alias Routing via Service Registry

> **⚠ Superseded** — 2026-05-07.  Pre-migration decision; no longer
> applies to the gRPC + Consul + Nomad architecture.  See the existing
> Status note below for the immediate successor, and
> [`docs/changelog.md`](../changelog.md) +
> [`docs/adr/AUDIT.md`](AUDIT.md) for the full triage.  Kept here for
> git archaeology.

## Status

Superseded — alias routing was a workaround for RabbitMQ's lack of structured method names. With gRPC, every method has a fully-qualified name (`<package>.<service>/<method>`); no aliasing layer required. Generated services do not include an `alias.json`.

## Date

2026-02-12

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-12 | 1.0 | Initial version |

## Context

Users need to create **simplified shortcuts** for service method calls:

- Reduce a multi-parameter method to fewer parameters by fixing some values
- Rename a method to a domain-specific name (e.g. `turn_on` instead of
  `svc_api_set_switch` with specific device IDs)
- Call an alias without knowing which service implements the underlying method

**Example:** A hardware service exposes:

```
svc_api_set_switch(device_id, port, state)
```

A test engineer wants a simpler call:

```
turn_on_led(state)
```

where `device_id=710925` and `port=17` are fixed, and only `state` is
user-provided.

The question is: where should alias resolution live, and how should the
`${input}` placeholder mechanism work?

## Decision

Alias routing is implemented **inside the Service Registry** as an extension
of its request dispatch, using a JSON configuration file (`alias.json`).

### Alias Configuration Format

```json
{
    "turn_on_led": {
        "Service name": "ServiceCleware",
        "Method name": "svc_api_set_switch",
        "Arguments": "710925,17,${input}"
    },
    "quick_add": {
        "Service name": "Calculator",
        "Method name": "svc_api_add",
        "Arguments": "${input},${input}"
    }
}
```

Each alias maps:
- **Alias name** (key) → the virtual method name callers use
- **Service name** → target service that handles the real method
- **Method name** → actual `svc_api_*` method on the target service
- **Arguments** → comma-separated template with `${input}` placeholders

### The `${input}` Placeholder

`${input}` marks positions where the caller must provide a value at runtime.
All other values are **fixed constants**.

**Substitution mechanism:**

```python
alias_args_string = "710925,17,${input}"
actual_args = ["1"]  # caller provides one argument

# Replace ${input} with {} for Python format()
modified = alias_args_string.replace("${input}", "{}").format(*actual_args)
# Result: "710925,17,1"

args_list = modified.split(',')
# Result: ["710925", "17", "1"]
```

**Examples:**

| Original method | Alias arguments | Caller provides | Result args |
|----------------|-----------------|-----------------|-------------|
| `add(a, b)` | `${input},${input}` | `[3, 5]` | `[3, 5]` |
| `add(a, b)` | `${input},4` | `[3]` | `[3, 4]` |
| `set_switch(dev, port, state)` | `710925,17,${input}` | `[1]` | `[710925, 17, 1]` |
| `get_status()` | (empty) | `[]` | `[]` |

### Request Flow

```
Caller                     Registry                      Target Service
  │                           │                               │
  │  RPC: method="turn_on_led"│                               │
  │        args=["1"]         │                               │
  │ ─────────────────────────>│                               │
  │                           │                               │
  │            is_specific_request("turn_on_led")             │
  │            → True (exists in _alias_dict)                 │
  │                           │                               │
  │            Resolve target:│                               │
  │            service = "ServiceCleware"                      │
  │            method  = "svc_api_set_switch"                  │
  │            args    = "710925,17,${input}"                  │
  │                           │                               │
  │            Substitute:    │                               │
  │            args → ["710925","17","1"]                      │
  │                           │                               │
  │            Resolve routing_key from                        │
  │            services_information["ServiceCleware"]          │
  │                           │                               │
  │                           │  RPC: method="svc_api_set_switch"
  │                           │        args=["710925","17","1"]
  │                           │ ─────────────────────────────>│
  │                           │                               │
  │                           │  Response: {"result":"pass"}  │
  │                           │ <─────────────────────────────│
  │                           │                               │
  │  Response (forwarded)     │                               │
  │ <─────────────────────────│                               │
```

### Integration with ServiceBase Dispatch

Alias routing uses the `on_specific_request()` hook in `ServiceBase`:

```python
# ServiceBase.dispatch_request()
if method_name in self._api_dict:
    return call_method(method_name, args)

if self.is_specific_request(method_name):
    return None  # → triggers on_specific_request()

# ServiceRegistry overrides:
def is_specific_request(self, request):
    return request in self._alias_dict

def on_specific_request(self, request, body):
    return self.handle_alias_request(body)
```

This keeps alias routing in the domain layer without modifying the base
dispatch logic.

### GUI Management

The ServiceAlias GUI (`web/services/ServiceAlias1.0.0/`) provides:
- Table editor for alias name, target service, method, and arguments
- Apply button saves to `alias.json` via `svc_api_update_alias_conf()`
- Code Helper generates example code (Python, JavaScript, Robot Framework)
  showing how to call each alias with the correct number of `${input}` args

## Why Aliases Live in the Registry

### Alternative: Separate Alias Proxy Service (Rejected)

A dedicated proxy service between clients and target services.

Rejected because:
- Adds another service to deploy and manage
- The registry already knows all service routing keys (it tracks
  `services_information`), so it can resolve targets without external lookup
- Alias routing is a natural extension of the registry's dispatch chain

### Alternative: Client-Side Alias Resolution (Rejected)

The GUI or client library resolves aliases locally before sending RPC.

Rejected because:
- Every client must load and parse `alias.json`
- Alias updates require restarting or refreshing every client
- Clients must know target service routing keys (breaks encapsulation)
- Robot Framework and Python test scripts cannot easily do client-side alias
  resolution

### Alternative: Decorator-Based Aliases in Services (Rejected)

```python
@alias("turn_on_led", args="710925,17,${input}")
def svc_api_set_switch(self, dev, port, state): ...
```

Rejected because:
- Aliases are a **cross-service concern** (an alias can target any service)
- Service authors should not need to know about aliases
- Alias configuration should be changeable without restarting services

## Consequences

### Positive

- **Centralized** — all aliases managed in one place (registry + alias.json)
- **Transparent** — callers don't know they're using an alias; the RPC interface
  is identical
- **Dynamic** — aliases can be added/modified via GUI without restarting services
- **Flexible** — `${input}` allows any combination of fixed and variable arguments
- **No client changes** — Robot Framework, Python scripts, and GUI all call aliases
  the same way they call regular methods

### Negative

- **Single point of routing** — all alias calls go through the registry, adding
  one RPC hop (client → registry → target → registry → client)
- **String-based arguments** — all arguments are passed as strings after
  `split(',')`. Target methods must handle type conversion.
- **No validation** — alias arguments are not validated against the target
  method's signature until runtime

### Neutral

- The registry must be running for aliases to work (same requirement as for
  service discovery)
- Alias configuration is per-registry instance (not shared across brokers in a
  multi-broker setup)

## References

- Source: `MicroserviceBase/domain/service_registry.py` (lines 86-93, 199-260)
- Source: `MicroserviceBase/domain/service_base.py` (lines 419-495)
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/services/ServiceAlias1.0.0/`
- Related: ADR-003 (Custom Service Registry), ADR-017 (svc_api_ Convention)
