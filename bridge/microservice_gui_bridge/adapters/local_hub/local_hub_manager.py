"""
Local Hub Manager — manages a local ProcessHub instance lifecycle.

Wraps ProcessHub APIs (lazy import) so the MicroserviceManager GUI can
start/stop a ProcessHub on the local machine, manage processes, and
optionally join a fleet as an agent.
"""

import copy
import json
import logging
import os
import sys
import threading
import time
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
                from ProcessHub.process import SimpleExecutor
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
            self._executor = SimpleExecutor(stop_timeout=5.0)
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
