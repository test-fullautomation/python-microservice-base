# ADR-008: Service Import with Module Execution Pattern

## Status

Accepted

## Date

2026-02-05

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-05 | 1.0 | Initial version |
| 2026-02-08 | 1.1 | Added service_name detection via AST |

## Context

Users need to import existing microservice packages into the Local Hub for management. Initially, services were launched as `python main.py`, but this causes import failures when the service uses relative imports (e.g., `from .ServiceCleware import ServiceCleware`).

Additionally, the hub process name (folder name) often differs from the service's internal name (`_SERVICE_INFO['name']`), causing RPC shutdown to fail (see ADR-006).

## Decision

### Execution Pattern: `python -m <package>`

Run imported services as Python modules from the parent directory:

```
python -m ClewareSwitch
         ↑ package folder name
```

Config entry:
```json
{
    "script": "${python}",
    "args": ["-m", "ClewareSwitch"],
    "cwd": "${config_dir}/services",
    "service_name": "ServiceCleware"
}
```

This requires a `__main__.py` in the service package.

### Import Workflow

```
1. Validate service structure
   ├── Check for __main__.py or main.py
   ├── AST parse for syntax errors
   ├── Detect _SERVICE_INFO['name'] via AST
   └── Warn if ServiceBase import missing

2. Copy files to services/{name}/
   ├── shutil.copytree(source, target)
   └── Handle nested ZIP root folders

3. Auto-generate __main__.py if needed
   ├── If only main.py exists → generate wrapper
   └── If __main__.py has wrong package imports → regenerate

4. Create hub config entry
   ├── script: ${python}
   ├── args: ["-m", name]
   ├── cwd: ${config_dir}/services
   └── service_name: detected _SERVICE_INFO['name']
```

### AST-Based Service Name Detection

The `_validate_service_structure` method scans `.py` files for `_SERVICE_INFO` dict assignments and extracts the `'name'` value:

```python
for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if getattr(target, 'id', None) == '_SERVICE_INFO':
                if isinstance(node.value, ast.Dict):
                    # Extract 'name' key value
                    detected_service_name = ...
```

This detected name is stored as `service_name` in the config, enabling correct RPC shutdown routing (see ADR-006).

### Auto-Generated `__main__.py`

When only `main.py` exists, or when the existing `__main__.py` has hardcoded imports for a different package name:

```python
"""Auto-generated entry point for python -m execution."""
import os
import sys

# Ensure the service directory is on sys.path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

main()
```

### Two Import Modes (GUI)

1. **Folder Path**: User provides absolute path; backend copies files
2. **ZIP Upload**: User drops a `.zip`; backend decodes base64, extracts, detects nested root folder

## Consequences

### Positive

- Relative imports work correctly (`from .module import Class`)
- Service name mismatch is detected and stored automatically
- RPC shutdown routes to the correct queue
- Both folder and ZIP import are supported

### Negative

- AST parsing adds complexity to validation
- Auto-generated `__main__.py` may not handle all edge cases
- Service must be importable as a Python package

### Neutral

- Existing manually-configured processes are unaffected (no `cwd` → old path)
- `service_name` field is optional; falls back to process name if absent

## Alternatives Considered

### 1. `python main.py` Execution (Rejected)

Run service directly with `python path/to/main.py`.

Rejected because:
- Relative imports fail (`from .ServiceCleware import ...`)
- `sys.path` doesn't include the service's parent directory

### 2. PYTHONPATH Injection (Rejected)

Set `PYTHONPATH` environment variable to include the service directory.

Rejected because:
- `sys.path.insert()` in the parent process does NOT affect subprocesses
- Must pass via `env` dict, which is fragile and non-portable

## References

- Source: `MicroserviceBase/adapters/local_hub/local_hub_manager.py` (import_service, _validate_service_structure)
- Source: `MicroserviceBase/MicroserviceManagerGUI/web/js/LocalHubDashboard.js` (import UI)
- Related: ADR-006 (Service Executor), ADR-007 (Local Hub Manager)
