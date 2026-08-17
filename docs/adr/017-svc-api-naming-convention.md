# ADR-017: svc_api_ Naming Convention for Method Discovery

> **⚠ Superseded** — 2026-05-07.  Pre-migration decision; no longer
> applies to the gRPC + Consul + Nomad architecture.  See the existing
> Status note below for the immediate successor, and
> [`docs/changelog.md`](../reference/changelog.md) +
> [`docs/adr/AUDIT.md`](AUDIT.md) for the full triage.  Kept here for
> git archaeology.

## Status

Superseded — gRPC service+method names are explicit in `.proto`, so the `svc_api_` prefix convention (used to auto-discover callable methods on RabbitMQ-era services) is no longer needed. Generated scaffolds use plain method names matching the `.proto`.

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

Microservices need to expose API methods that can be:

1. **Called remotely** via RPC (the broker delivers the request)
2. **Discovered automatically** by the GUI and other clients
3. **Documented** with parameter names, types, and descriptions
4. **Filtered** — some methods (shutdown, GUI file delivery) should be
   callable but not listed as public API

The question is: how should a service declare which methods are part of its
public API?

## Decision

Use a **naming convention** — methods prefixed with `svc_api_` are
automatically discovered as API endpoints via Python reflection.

### Discovery Mechanism

```python
def get_svc_api_methods_dict(self):
    methods = {
        method: getattr(self, method)
        for method in dir(self)
        if method.startswith('svc_api') and callable(getattr(self, method))
    }
    if not self._SERVICE_INFO['gui_support']:
        methods.pop('svc_api_get_gui_files', None)
    if not self._SERVICE_INFO.get('downloadable', False):
        methods.pop('svc_api_get_service_files', None)
    return methods
```

At initialization, `ServiceBase` calls `dir(self)` to enumerate all attributes,
filters for `svc_api` prefix + callable, and builds `_api_dict` — a dict
mapping method name to bound method.

### Internal Methods

Four methods are **dispatchable** (can be called via RPC) but **hidden** from
the published API list:

```python
_internal = {
    'svc_api_get_gui_files',      # ZIP of GUI HTML/CSS/JS
    'svc_api_get_gui_checksum',   # MD5 checksum for cache invalidation
    'svc_api_shutdown',           # Graceful service shutdown
    'svc_api_get_service_files',  # ZIP of entire service package
}
```

These are filtered from `_SERVICE_INFO['methods']` so the GUI's API Explorer
doesn't show them, but they remain in `_api_dict` so RPC calls still work.

### Request Dispatch

When a request arrives:

```python
def dispatch_request(self, body):
    method_name = body['method']
    args = body['args']

    if method_name in self._api_dict:
        if not args:
            result = self._api_dict[method_name]()
        elif isinstance(args, str):
            result = self._api_dict[method_name](args)
        else:
            result = self._api_dict[method_name](*args)
        return ServiceResponse(method_name, 'pass', result)

    if self.is_specific_request(method_name):
        return None  # delegate to on_specific_request()

    return ServiceResponse(method_name, 'fail', 'Non-supported request')
```

Three-level fallback:
1. Look up in `_api_dict` (standard `svc_api_*` method)
2. Check `is_specific_request()` (subclass hook — used by alias routing)
3. Return failure

### Docstring-Based Metadata

Parameter metadata is extracted from docstrings using a regex pattern:

```
* ``param_name``

  / *Condition*: required / *Type*: str / *Default*: None /

  Description of the parameter.
```

The parsed result populates `_SERVICE_INFO['methods_info']`:

```python
{
    'svc_api_add': {
        'arguments': [
            {'name': 'a', 'condition': 'required', 'type': 'int',
             'default': None, 'description': 'First number'},
            {'name': 'b', 'condition': 'required', 'type': 'int',
             'default': None, 'description': 'Second number'},
        ],
        'return_type': 'int'
    }
}
```

This metadata feeds the GUI's API Explorer and the Code Helper's generated
examples.

### Example

```python
class CalculatorService(ServiceBase):
    _SERVICE_INFO = {
        'name': 'Calculator',
        'version': '1.0.0',
        'routing_key': 'service.calculator',
        'gui_support': False,
        'methods': [],       # auto-populated at init
        'methods_info': {},   # auto-populated at init
    }

    def svc_api_add(self, a, b):
        """
Add two numbers.

**Arguments:**

* ``a``

  / *Condition*: required / *Type*: int /

  First number.

* ``b``

  / *Condition*: required / *Type*: int /

  Second number.

**Returns:**

  / *Type*: int /

  Sum of a and b.
        """
        return int(a) + int(b)

    def svc_api_multiply(self, a, b):
        """Multiply two numbers."""
        return int(a) * int(b)

    def _internal_helper(self):
        """Not exposed — no svc_api_ prefix."""
        pass
```

At initialization:
- `_api_dict` = `{'svc_api_add': <bound>, 'svc_api_multiply': <bound>,
  'svc_api_shutdown': <bound>, ...}`
- `_SERVICE_INFO['methods']` = `['svc_api_add', 'svc_api_multiply']`
  (shutdown filtered out)
- `_SERVICE_INFO['methods_info']` = parsed docstring metadata for each public
  method

## Comparison with Alternatives

| Approach | Discovery | Metadata | Filtering | Boilerplate |
|----------|-----------|----------|-----------|-------------|
| **`svc_api_` convention** | Automatic (`dir()` + prefix) | Docstring parsing | Internal set | Zero (just name the method) |
| **Decorator** (`@api_method`) | Explicit registration | Decorator args | Decorator flag | One line per method |
| **Config file** (methods.yaml) | External file | In file | In file | Separate file to maintain |
| **Protocol Buffers** (.proto) | Code generation | Schema-defined | Schema-defined | Proto file + codegen step |
| **Type annotations** | Introspection | Type hints | Custom marker | Type hints on each param |

### Decorators (Rejected)

```python
@api_method(description="Add two numbers")
def add(self, a: int, b: int) -> int: ...
```

Rejected because:
- Adds boilerplate to every method
- Requires importing the decorator
- Discovery still needs introspection (checking for decorator marker)
- Docstring convention already provides richer metadata (condition, default)

### Configuration File (Rejected)

```yaml
methods:
  - name: svc_api_add
    args: [a, b]
    description: Add two numbers
```

Rejected because:
- Metadata is separated from the code (can become stale)
- Extra file to maintain per service
- No advantage over docstring-based approach for our use case

### Protocol Buffers (Rejected)

```protobuf
service Calculator {
  rpc Add(AddRequest) returns (AddResponse);
}
```

Rejected because:
- Requires code generation step (protoc)
- Schema-first conflicts with our runtime discovery model
- Services cannot dynamically add methods without regenerating code
- Adds protobuf dependency to every service

## Consequences

### Positive

- **Zero boilerplate** — naming a method `svc_api_*` is all it takes to expose it
- **Automatic discovery** — GUI and API Explorer show methods without configuration
- **Self-documenting** — docstrings serve as both developer docs and machine-readable metadata
- **Clean separation** — internal methods (no prefix) are invisible to clients
- **Consistent** — all services follow the same pattern, making the codebase predictable

### Negative

- **Convention-dependent** — a typo in the prefix (`svc_ap_add`) silently fails to register
- **Docstring coupling** — metadata extraction depends on a specific docstring format; non-conforming docstrings produce empty metadata
- **No compile-time validation** — method signatures and types are not checked until runtime

### Neutral

- The `_internal` set (4 methods) is hardcoded in `ServiceBase`. Adding new internal methods requires updating this set.
- Services can override `is_specific_request()` and `on_specific_request()` for custom routing beyond the convention (e.g. alias routing in ServiceRegistry).

## References

- Source: `MicroserviceBase/domain/service_base.py` (lines 51-54, 96-103, 211-278, 445-495)
- Source: `MicroserviceBase/domain/models.py` (ServiceInfo, ServiceMethod, MethodArgument)
- Related: ADR-001 (Hexagonal Architecture), ADR-018 (Alias Routing)
