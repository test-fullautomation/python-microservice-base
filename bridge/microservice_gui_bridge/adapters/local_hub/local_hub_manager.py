"""
Local Hub Manager — manages a local ProcessHub instance lifecycle.

Wraps ProcessHub APIs (lazy import) so the MicroserviceManager GUI can
start/stop a ProcessHub on the local machine, manage processes, and
optionally join a fleet as an agent.
"""

import ast
import base64
import copy
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LocalHubManager:
    """Manages a local ProcessHub instance lifecycle."""

    def __init__(self, config_path=None):
        self._server = None
        self._executor = None
        self._transport = None
        self._agent = None
        self._fleet_transport = None
        self._running = False
        self._mode = None          # "standalone" or "agent"
        self._hub_id = None
        self._hub_name = None
        self._process_config = {}
        self._raw_config = {}      # unresolved values for saving
        self._config_path = config_path
        self._tick_thread = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_hub(
        self,
        mode: str = "standalone",
        xpub_port: int = 5555,
        xsub_port: int = 5556,
        orchestrator_url: str = "",
        hub_id: str = "",
        hub_name: str = "",
        process_config: Optional[dict] = None,
    ) -> dict:
        """Start a local ProcessHub server.

        Args:
            mode: "standalone" or "agent" (join fleet).
            xpub_port: ZMQ XPUB port for the broker.
            xsub_port: ZMQ XSUB port for the broker.
            orchestrator_url: Fleet orchestrator ZMQ address (agent mode).
            hub_id: Hub identifier (agent mode).
            hub_name: Human-readable hub name (agent mode).
            process_config: Dict of {name: config} for processes.

        Returns:
            Status dict.
        """
        with self._lock:
            if self._running:
                return {"error": "Hub is already running"}

            try:
                # Lazy imports — ProcessHub is an optional dependency
                from ProcessHub.runtime import ProcessHubServer
                from ProcessHub.transport import ZmqTransport
                from .service_executor import ServiceExecutor
            except ImportError:
                return {
                    "error": (
                        "ProcessHub is not installed. "
                        "Install it with: pip install ProcessHub"
                    )
                }

            # Load persisted configs from file, then merge any passed overrides
            self._process_config = self._load_config_file()
            if process_config:
                self._process_config.update(process_config)
                self._raw_config.update(process_config)
                self._save_config_file()
            self._mode = mode
            self._hub_id = hub_id or f"local-hub-{int(time.time())}"
            self._hub_name = hub_name or "Local Hub"

            # Create components
            broker_host, broker_port = self._get_broker_config()
            config_dir = os.path.dirname(os.path.abspath(self._config_path)) if self._config_path else os.path.abspath('.')
            log_dir = os.path.join(config_dir, 'logs')
            self._executor = ServiceExecutor(
                broker_host=broker_host,
                broker_port=broker_port,
                stop_timeout=5.0,
                log_dir=log_dir,
            )
            self._transport = ZmqTransport(
                start_broker=True,
                xpub_port=xpub_port,
                xsub_port=xsub_port,
            )

            self._server = ProcessHubServer(
                transport=self._transport,
                executor=self._executor,
                process_config=self._process_config,
                refresh_interval=0.5,
            )

            self._server.start()
            self._running = True

            # Start tick loop in a daemon thread
            self._tick_thread = threading.Thread(
                target=self._tick_loop, daemon=True
            )
            self._tick_thread.start()

            # Agent mode: join a fleet orchestrator
            if mode == "agent" and orchestrator_url:
                self._start_agent(orchestrator_url, xpub_port, xsub_port)

            logger.info(
                "Local hub started (mode=%s, hub_id=%s)", mode, self._hub_id
            )
            return self.get_status()

    def stop_hub(self) -> dict:
        """Stop the local hub."""
        with self._lock:
            if not self._running:
                return {"error": "Hub is not running"}

            self._running = False

            if self._agent is not None:
                try:
                    self._agent.stop()
                except Exception:
                    logger.debug("Error stopping agent", exc_info=True)
                self._agent = None

            if self._fleet_transport is not None:
                try:
                    self._fleet_transport.stop()
                except Exception:
                    logger.debug("Error stopping fleet transport", exc_info=True)
                self._fleet_transport = None

            if self._server is not None:
                try:
                    self._server.stop()
                except Exception:
                    logger.debug("Error stopping server", exc_info=True)
                self._server = None

            self._executor = None
            self._transport = None
            self._mode = None

            logger.info("Local hub stopped")
            return {"status": "stopped"}

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Get current hub status."""
        if not self._running or self._server is None:
            return {
                "running": False,
                "mode": None,
                "hub_id": None,
                "hub_name": None,
                "processes": [],
                "connections": [],
                "configured_processes": [],
                "process_configs": {},
                "config_path": self._config_path or "",
            }

        snapshot = self._server.core.get_state_snapshot()

        # snapshot.processes is a tuple of ProcessSnapshot (name, state, pid)
        processes = []
        for proc in snapshot.processes:
            processes.append({
                "name": proc.name,
                "state": str(proc.state.value) if hasattr(proc.state, 'value') else str(proc.state),
                "pid": proc.pid,
            })

        # Include configured-but-not-running processes
        running_names = {p["name"] for p in processes}
        for name in self._process_config:
            if name not in running_names:
                processes.append({"name": name, "state": "stopped", "pid": None})

        # snapshot.connections is a tuple of ConnectionSnapshot (panel_id, ...)
        connections = [conn.panel_id for conn in snapshot.connections]

        return {
            "running": True,
            "mode": self._mode,
            "hub_id": self._hub_id,
            "hub_name": self._hub_name,
            "processes": processes,
            "connections": connections,
            "configured_processes": list(self._process_config.keys()),
            "process_configs": {
                k: _sanitize_config(v) for k, v in self._process_config.items()
            },
            "config_path": self._config_path or "",
        }

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------

    def start_processes(self, names: list) -> dict:
        """Start named processes."""
        if not self._running or self._server is None:
            return {"error": "Hub is not running"}

        results = {}
        for name in names:
            config = self._process_config.get(name, {})
            if not config:
                results[name] = {"success": False, "message": f"No config for {name}"}
                continue

            success, msg, pid = self._executor.start(name, config)
            results[name] = {"success": success, "message": msg, "pid": pid}

            if success and pid:
                self._server.register_admin_process(name, pid)

        return results

    def stop_processes(self, names: list, force: bool = False) -> dict:
        """Stop named processes."""
        if not self._running or self._server is None:
            return {"error": "Hub is not running"}

        results = {}
        for name in names:
            success, msg = self._executor.stop(name, force=force)
            results[name] = {"success": success, "message": msg}

            if success:
                self._server.unregister_admin_process(name)

        return results

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    def get_config(self) -> dict:
        """Get all process configurations."""
        return {
            k: _sanitize_config(v) for k, v in self._process_config.items()
        }

    def add_config(self, name: str, config: dict) -> dict:
        """Add a new process configuration."""
        if name in self._process_config:
            return {"success": False, "message": f"'{name}' already exists"}
        if not config.get("script"):
            return {"success": False, "message": "Script path is required"}

        self._process_config[name] = config
        self._raw_config[name] = config
        self._save_config_file()
        return {"success": True, "message": f"Config '{name}' added"}

    def update_config(self, name: str, config: dict) -> dict:
        """Update an existing process configuration."""
        if name not in self._process_config:
            return {"success": False, "message": f"'{name}' not found"}
        if not config.get("script"):
            return {"success": False, "message": "Script path is required"}

        self._process_config[name] = config
        self._raw_config[name] = config
        self._save_config_file()
        return {"success": True, "message": f"Config '{name}' updated"}

    def remove_config(self, name: str) -> dict:
        """Remove a process configuration."""
        if name not in self._process_config:
            return {"success": False, "message": f"'{name}' not found"}
        if self._executor and self._executor.is_running(name):
            return {"success": False, "message": f"'{name}' is still running"}

        del self._process_config[name]
        self._raw_config.pop(name, None)
        self._save_config_file()
        return {"success": True, "message": f"Config '{name}' removed"}

    def remove_service(self, name: str) -> dict:
        """Remove a service — delete config and managed service folder.

        Only deletes the folder if it lives inside the managed
        ``<config_dir>/services/`` directory (never touches external paths).
        Stops the process first if it is still running.
        """
        if name not in self._process_config:
            return {"success": False, "message": f"'{name}' not found"}

        # Stop if still running
        if self._executor and self._executor.is_running(name):
            self._executor.stop(name, force=True)

        # Remove from ProcessHub server's internal registry so it no
        # longer appears in get_state_snapshot().processes
        if self._server is not None:
            try:
                self._server.unregister_admin_process(name)
            except Exception:
                pass
            try:
                self._server.core._registry.remove(name)
            except Exception:
                pass

        # Remove config entry
        del self._process_config[name]
        self._raw_config.pop(name, None)
        self._save_config_file()

        # Delete service folder if inside managed services directory
        services_dir = self.get_services_dir()
        service_dir = os.path.join(services_dir, name)
        folder_deleted = False
        if os.path.isdir(service_dir):
            try:
                shutil.rmtree(service_dir)
                folder_deleted = True
                logger.info("Deleted service folder: %s", service_dir)
            except Exception as exc:
                logger.error("Failed to delete %s: %s", service_dir, exc)
                return {
                    "success": True,
                    "message": (
                        f"Config '{name}' removed, but failed to delete "
                        f"service folder: {exc}"
                    ),
                }

        msg = f"Service '{name}' removed"
        if folder_deleted:
            msg += " (config + files)"
        return {"success": True, "message": msg}

    def get_service_log(self, name: str, tail: int = 100) -> dict:
        """Read the last *tail* lines of a process log file."""
        if not self._executor:
            return {"name": name, "log": "", "log_file": ""}
        log_path = self._executor.get_log_path(name) or ""
        log_text = self._executor.read_log(name, tail=tail)
        return {"name": name, "log": log_text, "log_file": log_path}

    # ------------------------------------------------------------------
    # Service import
    # ------------------------------------------------------------------

    def get_services_dir(self) -> str:
        """Return absolute path to ``<config_dir>/services/``, creating it if needed."""
        if not self._config_path:
            base = os.path.abspath('.')
        else:
            base = os.path.dirname(os.path.abspath(self._config_path))
        services_dir = os.path.join(base, 'services')
        os.makedirs(services_dir, exist_ok=True)
        return services_dir

    def _validate_service_structure(self, service_dir: str) -> dict:
        """Validate that *service_dir* contains a valid microservice.

        Hard checks (fail on error):
        - ``__main__.py`` or ``main.py`` must exist.
        - The entry-point file must parse without syntax errors.

        Soft checks (warn only):
        - At least one ``.py`` file should import ``ServiceBase``.
        - At least one ``.py`` file should define ``_SERVICE_INFO``.

        Returns ``{"valid": True, "warnings": [...], "needs_dunder_main": bool}``
        or raises ``ValueError``.
        """
        has_dunder_main = os.path.isfile(os.path.join(service_dir, '__main__.py'))
        has_main = os.path.isfile(os.path.join(service_dir, 'main.py'))

        if not has_dunder_main and not has_main:
            raise ValueError(
                "Neither __main__.py nor main.py found in service folder"
            )

        # Syntax-check the entry point(s)
        for fname in ('__main__.py', 'main.py'):
            fpath = os.path.join(service_dir, fname)
            if not os.path.isfile(fpath):
                continue
            with open(fpath, 'r', encoding='utf-8') as f:
                source = f.read()
            try:
                ast.parse(source, filename=fname)
            except SyntaxError as exc:
                raise ValueError(f"{fname} has syntax errors: {exc}")

        # Soft checks — scan all .py files
        warnings = []
        has_service_base = False
        has_service_info = False
        for fname in os.listdir(service_dir):
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(service_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue
            if 'ServiceBase' in content:
                has_service_base = True
            if '_SERVICE_INFO' in content:
                has_service_info = True

        if not has_service_base:
            warnings.append("No .py file imports ServiceBase — this may not be a standard microservice")
        if not has_service_info:
            warnings.append("No .py file defines _SERVICE_INFO")

        # Detect _SERVICE_INFO['name'] via AST so we know the service's
        # actual RabbitMQ queue name (which may differ from the folder name).
        detected_service_name = None
        for fname in os.listdir(service_dir):
            if not fname.endswith('.py') or detected_service_name:
                continue
            fpath = os.path.join(service_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    source = f.read()
                if '_SERVICE_INFO' not in source:
                    continue
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Assign):
                        continue
                    for target in node.targets:
                        tname = getattr(target, 'id', None) or getattr(target, 'attr', None)
                        if tname != '_SERVICE_INFO':
                            continue
                        # _SERVICE_INFO = { 'name': '...', ... }
                        if isinstance(node.value, ast.Dict):
                            for key, val in zip(node.value.keys, node.value.values):
                                if (isinstance(key, (ast.Constant, ast.Str)) and
                                        (getattr(key, 'value', None) or getattr(key, 's', None)) == 'name' and
                                        isinstance(val, (ast.Constant, ast.Str))):
                                    detected_service_name = getattr(val, 'value', None) or getattr(val, 's', None)
                                    break
                        if detected_service_name:
                            break
                    if detected_service_name:
                        break
            except Exception:
                continue

        # Flag whether we need to auto-generate __main__.py
        needs_dunder_main = not has_dunder_main and has_main

        # Detect the original package name used in __main__.py imports
        # (e.g. "from MicroserviceClewareSwitch.X import Y")
        original_package = None
        if has_dunder_main:
            dunder_path = os.path.join(service_dir, '__main__.py')
            try:
                with open(dunder_path, 'r', encoding='utf-8') as f:
                    source = f.read()
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        mod = getattr(node, 'module', None) or ''
                        if mod and '.' in mod:
                            original_package = mod.split('.')[0]
                            break
            except Exception:
                pass

        return {
            "valid": True,
            "warnings": warnings,
            "needs_dunder_main": needs_dunder_main,
            "original_package": original_package,
            "service_name": detected_service_name,
        }

    def import_service(
        self,
        name: str,
        source_path: str = "",
        zip_data: str = "",
        wait_time: float = 1.0,
    ) -> dict:
        """Import a microservice from a folder or base64-encoded ZIP.

        Validates structure, copies files into ``<config_dir>/services/{name}/``,
        and creates a hub config entry using the ``${python}`` placeholder.

        Returns ``{"success": bool, "message": str, "warnings": [...]}``.
        """
        if not name:
            return {"success": False, "message": "Service name is required.", "warnings": []}
        if name in self._process_config:
            return {"success": False, "message": f"'{name}' already exists in hub config", "warnings": []}

        target_dir = os.path.join(self.get_services_dir(), name)
        if os.path.exists(target_dir):
            return {
                "success": False,
                "message": f"Service directory already exists: {target_dir} (use a different name)",
                "warnings": [],
            }

        temp_dir = None
        source_dir = None

        try:
            if zip_data:
                # Decode and extract ZIP
                temp_dir = tempfile.mkdtemp(prefix='ms_import_')
                try:
                    raw = base64.b64decode(zip_data)
                except Exception as exc:
                    return {"success": False, "message": f"Failed to decode ZIP data: {exc}", "warnings": []}
                zip_path = os.path.join(temp_dir, 'upload.zip')
                with open(zip_path, 'wb') as f:
                    f.write(raw)
                try:
                    extract_dir = os.path.join(temp_dir, 'extract')
                    with zipfile.ZipFile(zip_path, 'r') as zf:
                        zf.extractall(extract_dir)
                except Exception as exc:
                    return {"success": False, "message": f"Failed to extract ZIP data: {exc}", "warnings": []}

                # Detect nested root folder
                entries = os.listdir(extract_dir)
                if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
                    source_dir = os.path.join(extract_dir, entries[0])
                else:
                    source_dir = extract_dir

            elif source_path:
                if not os.path.isdir(source_path):
                    return {"success": False, "message": f"Source path does not exist: {source_path}", "warnings": []}
                source_dir = source_path

            else:
                return {"success": False, "message": "No source provided (folder path or ZIP).", "warnings": []}

            # Validate
            validation = self._validate_service_structure(source_dir)

            # Copy to target
            try:
                shutil.copytree(source_dir, target_dir)
            except Exception as exc:
                return {"success": False, "message": f"Failed to copy service files: {exc}", "warnings": []}

            # Determine if __main__.py needs to be (re-)generated:
            # 1. No __main__.py exists (only main.py)
            # 2. Existing __main__.py has hardcoded imports for a different
            #    package name (e.g. "from MicroserviceClewareSwitch.X ...")
            #    that won't work when the folder is renamed
            orig_pkg = validation.get("original_package")
            needs_regen = validation.get("needs_dunder_main") or (
                orig_pkg and orig_pkg != name
            )

            if needs_regen:
                dunder_path = os.path.join(target_dir, '__main__.py')
                with open(dunder_path, 'w', encoding='utf-8') as f:
                    f.write(
                        '"""Auto-generated entry point for python -m execution."""\n'
                        'import os\n'
                        'import sys\n'
                        '\n'
                        '# Ensure the service directory is on sys.path for local imports\n'
                        'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n'
                        '\n'
                        'from main import main\n'
                        '\n'
                        'main()\n'
                    )
                if orig_pkg and orig_pkg != name:
                    validation["warnings"].append(
                        f"__main__.py was regenerated — original had imports "
                        f"for '{orig_pkg}' which differs from '{name}'"
                    )
                else:
                    validation["warnings"].append(
                        "__main__.py was auto-generated (wraps main.main())"
                    )
                logger.info("Generated __main__.py for service '%s'", name)

            # Build config entry — run as: python -m <name> (from services dir)
            services_dir = self.get_services_dir()
            detected_svc_name = validation.get("service_name")
            resolved_config = {
                "script": sys.executable,
                "args": ["-m", name],
                "cwd": services_dir,
                "process_name": name,
                "wait_time": wait_time,
            }
            raw_config = {
                "script": "${python}",
                "args": ["-m", name],
                "cwd": "${config_dir}/services",
                "process_name": name,
                "wait_time": wait_time,
            }
            # Store the service's actual RabbitMQ queue name if it differs
            # from the hub process name (used by ServiceExecutor for RPC shutdown)
            if detected_svc_name and detected_svc_name != name:
                resolved_config["service_name"] = detected_svc_name
                raw_config["service_name"] = detected_svc_name
                logger.info(
                    "Service '%s' has internal name '%s' — stored as service_name",
                    name, detected_svc_name,
                )

            self._process_config[name] = resolved_config
            self._raw_config[name] = raw_config
            self._save_config_file()

            # Update the running server's config if hub is active
            if self._server is not None:
                try:
                    self._server.core.update_process_config(name, resolved_config)
                except Exception:
                    pass  # non-critical

            logger.info("Service '%s' imported from %s", name, source_dir)
            return {
                "success": True,
                "message": f"Service '{name}' imported successfully.",
                "warnings": validation.get("warnings", []),
                "config": raw_config,
            }

        except ValueError as exc:
            return {"success": False, "message": str(exc), "warnings": []}
        except Exception as exc:
            logger.exception("Unexpected error importing service '%s'", name)
            return {"success": False, "message": f"Import failed: {exc}", "warnings": []}
        finally:
            if temp_dir and os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> dict:
        """Reset the hub (stop processes, clear connections)."""
        if not self._running or self._server is None:
            return {"error": "Hub is not running"}

        success, message = self._server.reset()
        return {"success": success, "message": message}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_broker_config(self):
        """Read broker settings from config.json next to the hub config file."""
        if not self._config_path:
            return 'localhost', 5672
        config_dir = os.path.dirname(os.path.abspath(self._config_path))
        config_json = os.path.join(config_dir, 'config.json')
        try:
            with open(config_json, 'r') as f:
                cfg = json.load(f)
            return cfg.get('broker_host', 'localhost'), int(cfg.get('broker_port', 5672))
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return 'localhost', 5672

    def _resolve_placeholders(self, value, config_dir):
        """Replace ${python} and ${config_dir} placeholders in a string."""
        if not isinstance(value, str):
            return value
        value = value.replace('${python}', sys.executable)
        value = value.replace('${config_dir}', config_dir)
        return value

    def _load_config_file(self):
        """Load process configurations from the JSON file.

        Resolves ``${python}`` to ``sys.executable`` and ``${config_dir}``
        to the directory containing the config file.  Also stores the raw
        (unresolved) entries in ``_raw_config`` so that ``_save_config_file``
        can preserve placeholders.

        Returns the resolved dict (empty dict if no file or on error).
        """
        if not self._config_path:
            return {}
        try:
            with open(self._config_path, 'r') as f:
                raw = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.debug("Could not load hub config from %s: %s",
                         self._config_path, exc)
            return {}

        self._raw_config = copy.deepcopy(raw)

        config_dir = os.path.dirname(os.path.abspath(self._config_path))
        resolved = {}
        for name, cfg in raw.items():
            entry = {}
            for k, v in cfg.items():
                if isinstance(v, list):
                    entry[k] = [self._resolve_placeholders(i, config_dir)
                                for i in v]
                else:
                    entry[k] = self._resolve_placeholders(v, config_dir)
            resolved[name] = entry
        return resolved

    def _save_config_file(self):
        """Persist process configurations to the JSON file.

        Saves ``_raw_config`` which preserves placeholder entries
        (``${python}``, ``${config_dir}``) for configs loaded from the
        original file, while new/updated entries are saved as-is.
        """
        if not self._config_path:
            return
        try:
            safe = {k: _sanitize_config(v)
                    for k, v in self._raw_config.items()}
            with open(self._config_path, 'w') as f:
                json.dump(safe, f, indent=2)
            logger.debug("Hub config saved to %s", self._config_path)
        except Exception as exc:
            logger.error("Failed to save hub config to %s: %s",
                         self._config_path, exc)

    def _tick_loop(self):
        """Non-blocking tick loop running in a daemon thread."""
        while self._running and self._server is not None:
            try:
                messages = self._server._core.tick()
                self._server._send_messages(messages)
                snapshot = self._server._core.get_state_snapshot()
                self._server._view.render(snapshot)
            except Exception:
                logger.debug("Tick loop error", exc_info=True)
            time.sleep(self._server._refresh_interval)

    def _start_agent(self, orchestrator_url, xpub_port, xsub_port):
        """Start a HubAgent to join a fleet orchestrator."""
        try:
            from ProcessHub.fleet import HubAgent
            from ProcessHub.transport import ZmqTransport

            self._fleet_transport = ZmqTransport(
                start_broker=False,
                connect_address=orchestrator_url,
            )
            self._fleet_transport.start()

            self._agent = HubAgent(
                transport=self._fleet_transport,
                server=self._server,
                hub_id=self._hub_id,
                hub_name=self._hub_name,
            )
            self._agent.start()
            logger.info("Fleet agent started, connected to %s", orchestrator_url)
        except ImportError:
            logger.warning("ProcessHub fleet package not available")
        except Exception:
            logger.exception("Failed to start fleet agent")


def _sanitize_config(config: dict) -> dict:
    """Return a JSON-safe copy of a process config."""
    safe = {}
    for k, v in config.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            safe[k] = v
        elif isinstance(v, (list, tuple)):
            safe[k] = [str(i) for i in v]
        elif isinstance(v, dict):
            safe[k] = {str(dk): str(dv) for dk, dv in v.items()}
        else:
            safe[k] = str(v)
    return safe
