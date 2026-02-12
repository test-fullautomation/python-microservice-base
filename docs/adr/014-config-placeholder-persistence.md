# ADR-014: Config Placeholder Persistence

## Status

Accepted

## Date

2026-02-01

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-01 | 1.0 | Initial version |

## Context

ProcessHub config files (`hub_processes.json`) contain paths to Python executables and service directories. If we resolve these paths at save time, the config becomes non-portable:

```json
{
    "script": "C:\\Program Files\\RobotFramework\\python3\\python.exe",
    "cwd": "D:\\Project\\robot\\github\\microsoft-base-develop\\MicroserviceBase\\MicroserviceManagerGUI\\python\\services"
}
```

This config breaks when:
- Moved to a different machine
- Python installation path changes
- Project directory is relocated

## Decision

Use **placeholder strings** in the config file, resolved at runtime:

| Placeholder | Resolved To | Example |
|---|---|---|
| `${python}` | `sys.executable` | `C:\Python312\python.exe` |
| `${config_dir}` | Directory of `hub_processes.json` | `D:\...\python` |

**Config file preserves placeholders:**
```json
{
    "script": "${python}",
    "args": ["-m", "ClewareSwitch"],
    "cwd": "${config_dir}/services"
}
```

**Implementation uses two dicts:**

```python
class LocalHubManager:
    self._raw_config = {}       # Preserves ${python}, ${config_dir}
    self._process_config = {}   # Resolved for runtime use

    def _load_config_file(self):
        raw = json.load(f)
        for name, cfg in raw.items():
            self._raw_config[name] = cfg
            self._process_config[name] = self._resolve_placeholders(cfg)

    def _save_config_file(self):
        json.dump(self._raw_config, f)  # Save originals, not resolved
```

## Consequences

### Positive

- Config files are portable across machines and Python installations
- Same `hub_processes.json` works on Windows, Linux, and macOS
- No manual path editing when moving the project

### Negative

- Two config dicts must stay in sync
- Placeholders only work in string values (not nested dicts)

### Neutral

- Manually-added configs with absolute paths still work (no placeholders)

## References

- Source: `MicroserviceBase/adapters/local_hub/local_hub_manager.py`
- Related: ADR-010 (Local Hub Manager)
