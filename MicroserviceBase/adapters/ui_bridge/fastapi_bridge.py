#  Copyright 2020-2025 Robert Bosch GmbH
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# *******************************************************************************
#
# File: fastapi_bridge.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   FastAPI implementation of UIBridgePort.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import asyncio
import base64
import importlib.metadata
import json
import logging
import os
import tempfile
import threading
import zipfile

from ...ports.ui_bridge import UIBridgePort

logger = logging.getLogger(__name__)


def _validate_safe_name(name: str) -> None:
   """
Reject names that could escape the intended directory.

Raises ``ValueError`` if *name* contains path separators or ``..``.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  The name to validate (e.g. service name, folder name).
   """
   if not name:
      raise ValueError("Name must not be empty")
   if os.sep in name or '/' in name or '\\' in name:
      raise ValueError(f"Name must not contain path separators: {name!r}")
   if '..' in name:
      raise ValueError(f"Name must not contain '..': {name!r}")


class FastAPIBridge(UIBridgePort):
   """
FastAPI implementation of UIBridgePort.

Exposes a REST API that any UI client (Electron, browser, mobile) can call.
Also provides a WebSocket endpoint for push-based service updates.

Endpoints:
   POST /api/request         - Route a service request through the transport
   GET  /api/services        - Get current services info
   WS   /ws/updates          - Real-time service update stream

Requires ``fastapi`` and ``uvicorn`` (optional dependencies).
   """

   def __init__(self, host='localhost', port=8000):
      """
Initialize the FastAPI bridge.

**Arguments:**

* ``host``

  / *Condition*: optional / *Type*: str / *Default*: 'localhost' /

  Host to bind the server to.

* ``port``

  / *Condition*: optional / *Type*: int / *Default*: 8000 /

  Port to bind the server to.
      """
      self._host = host
      self._port = port
      self._request_handler = None
      self._services_info_provider = None
      self._app = None
      self._server = None
      self._thread = None
      self._ws_clients = set()
      self._ws_clients_lock = threading.Lock()
      self._server_loop = None
      self._fleet_api_url = None

   def _build_app(self):
      """
Build the FastAPI application with all routes.
      """
      from fastapi import FastAPI, WebSocket, WebSocketDisconnect
      from fastapi.middleware.cors import CORSMiddleware
      from pydantic import BaseModel
      from typing import Any, Optional, List

      app = FastAPI(title="MicroserviceBase UI Bridge")

      app.add_middleware(
         CORSMiddleware,
         allow_origins=["*"],
         allow_credentials=True,
         allow_methods=["*"],
         allow_headers=["*"],
      )

      bridge = self

      # ---- Local Hub Manager (lazy init) ----
      self._local_hub_manager = None

      class ServiceRequestBody(BaseModel):
         method: str
         args: Optional[Any] = None
         exchange: str = "services_request"
         routing_key: str = ""

      class ServiceResponseBody(BaseModel):
         request: str = ""
         result: str = "pass"
         result_data: Any = ""

      @app.post("/api/request", response_model=ServiceResponseBody)
      def handle_request(body: ServiceRequestBody):
         """
Route a service request through the transport layer.
         """
         if bridge._request_handler is None:
            return ServiceResponseBody(
               request=body.method,
               result="exception",
               result_data="No request handler configured",
            )

         request_data = {"method": body.method, "args": body.args}
         try:
            result = bridge._request_handler(request_data, body.exchange, body.routing_key)
         except Exception as exc:
            logger.error("Request handler error for %s: %s", body.method, exc, exc_info=True)
            return ServiceResponseBody(
               request=body.method,
               result="exception",
               result_data=str(exc),
            )

         if isinstance(result, dict):
            return ServiceResponseBody(**result)
         return ServiceResponseBody(
            request=body.method,
            result="pass",
            result_data=result,
         )

      @app.get("/api/version")
      def get_version():
         """
Return the installed MicroserviceBase package version.
         """
         try:
            version = importlib.metadata.version("MicroserviceBase")
         except importlib.metadata.PackageNotFoundError:
            version = "unknown"
         return {"version": version}

      @app.get("/api/services")
      def get_services():
         """
Return current services information.
         """
         if bridge._services_info_provider is None:
            return {}
         return bridge._services_info_provider()

      @app.websocket("/ws/updates")
      async def ws_updates(websocket: WebSocket):
         """
WebSocket endpoint for real-time service update push.
         """
         await websocket.accept()
         with bridge._ws_clients_lock:
            bridge._ws_clients.add(websocket)
         try:
            while True:
               # Keep the connection alive; client doesn't need to send anything
               await websocket.receive_text()
         except WebSocketDisconnect:
            with bridge._ws_clients_lock:
               bridge._ws_clients.discard(websocket)
         except ConnectionError:
            logger.debug("WebSocket connection error", exc_info=True)
            with bridge._ws_clients_lock:
               bridge._ws_clients.discard(websocket)

      @app.post("/api/service-gui-download/{service_name}")
      def download_and_cache_gui(service_name: str, routing_key: str = ""):
         """
Download service GUI resources and extract them to the web/services/ directory.
         """
         try:
            _validate_safe_name(service_name)
         except ValueError as exc:
            return {"error": str(exc)}

         if bridge._request_handler is None:
            return {"error": "No request handler configured"}

         request_data = {"method": "svc_api_get_gui_files", "args": None}
         result = bridge._request_handler(
            request_data, "services_request", routing_key
         )

         if not isinstance(result, dict) or "result_data" not in result:
            return {"error": "Failed to retrieve GUI files"}

         if result.get("result") != "pass" or not result["result_data"]:
            return {"error": "Service returned no GUI files (check GUIs/ folder)"}

         gui_web_path = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'MicroserviceManagerGUI', 'web', 'services'
         )

         zip_fd, zip_path = tempfile.mkstemp(suffix='.zip')
         os.close(zip_fd)
         try:
            services_info = bridge._services_info_provider() if bridge._services_info_provider else {}
            version = ""
            if service_name in services_info:
               version = services_info[service_name].get("version", "")

            folder_name = service_name + version
            _validate_safe_name(folder_name)
            target_dir = os.path.join(gui_web_path, folder_name)
            os.makedirs(target_dir, exist_ok=True)

            zip_bytes = base64.b64decode(result["result_data"])
            with open(zip_path, "wb") as f:
               f.write(zip_bytes)

            with zipfile.ZipFile(zip_path, "r") as zf:
               # Zip-slip protection
               real_target = os.path.realpath(target_dir)
               for entry in zf.namelist():
                  real_entry = os.path.realpath(os.path.join(target_dir, entry))
                  if not real_entry.startswith(real_target + os.sep) and real_entry != real_target:
                     return {"error": f"Zip contains unsafe path: {entry!r}"}
               zf.extractall(target_dir)

            # Ensure the expected <ServiceName>.html/.js exist.
            # If the ZIP used different names (e.g. "service.html" instead
            # of "MyService.html"), create copies so the GUI can find them.
            expected_html = os.path.join(target_dir, service_name + ".html")
            expected_js = os.path.join(target_dir, service_name + ".js")
            if not os.path.isfile(expected_html):
               for f in os.listdir(target_dir):
                  if f.lower().endswith(".html"):
                     import shutil
                     shutil.copy2(os.path.join(target_dir, f), expected_html)
                     logger.info("Copied %s -> %s.html", f, service_name)
                     break
            if not os.path.isfile(expected_js):
               for f in os.listdir(target_dir):
                  if f.lower().endswith(".js"):
                     import shutil
                     shutil.copy2(os.path.join(target_dir, f), expected_js)
                     logger.info("Copied %s -> %s.js", f, service_name)
                     break

            logger.info("GUI resources extracted to %s", target_dir)
            return {"status": "ok", "path": target_dir}
         except Exception as exc:
            logger.error("Failed to extract GUI resources: %s", exc, exc_info=True)
            return {"error": str(exc)}
         finally:
            if os.path.exists(zip_path):
               os.remove(zip_path)

      # ---- Service GUI directory listing ----

      @app.get("/api/list-dir/{dir_path:path}")
      def list_service_gui_dir(dir_path: str):
         """List files in a service GUI subdirectory under web/."""
         gui_web_path = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'MicroserviceManagerGUI', 'web'
         )
         target = os.path.realpath(os.path.join(gui_web_path, dir_path))
         allowed = os.path.realpath(gui_web_path)
         if not target.startswith(allowed + os.sep):
            return {"error": "Path outside allowed directory"}
         if not os.path.isdir(target):
            return {"files": []}
         return {"files": [f for f in os.listdir(target) if os.path.isfile(os.path.join(target, f))]}

      # ---- Service GUI schema endpoint ----

      @app.get("/api/service-schema/{service_name}")
      def get_service_schema(service_name: str):
         """
Return gui_schema.json for a service.

If the service folder contains a gui_schema.json file, return its contents.
Otherwise, auto-generate a schema from the service's methods_info metadata.
         """
         try:
            _validate_safe_name(service_name)
         except ValueError as exc:
            return {"error": str(exc)}

         # Look for gui_schema.json in the service's GUI folder
         gui_web_path = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'MicroserviceManagerGUI', 'web', 'services'
         )

         services_info = bridge._services_info_provider() if bridge._services_info_provider else {}
         version = ""
         if service_name in services_info:
            version = services_info[service_name].get("version", "")

         folder_name = service_name + version
         schema_path = os.path.join(gui_web_path, folder_name, "gui_schema.json")

         if os.path.isfile(schema_path):
            try:
               with open(schema_path, 'r', encoding='utf-8') as f:
                  schema = json.load(f)
               return {"status": "ok", "schema": schema, "source": "file"}
            except Exception as exc:
               logger.warning("Failed to read gui_schema.json: %s", exc)

         # Auto-generate from methods_info
         if service_name in services_info:
            svc = services_info[service_name]
            methods = svc.get("methods", [])
            methods_info = svc.get("methods_info", {})

            if methods and methods_info:
               sections = []
               for method_name in methods:
                  m_info = methods_info.get(method_name, {})
                  fields = []
                  for arg in m_info.get("arguments", []):
                     arg_type = (arg.get("type", "str") or "str").lower()
                     widget_map = {
                        "int": "number", "float": "number",
                        "bool": "checkbox", "boolean": "checkbox",
                     }
                     fields.append({
                        "arg": arg.get("name", "arg"),
                        "label": " ".join(
                           w.capitalize()
                           for w in (arg.get("name", "arg")).split("_")
                        ),
                        "widget": widget_map.get(arg_type, "text"),
                        "placeholder": arg.get("description", ""),
                     })

                  label = " ".join(
                     w.capitalize()
                     for w in method_name.replace("svc_api_", "").replace("api_", "").split("_")
                  )
                  sections.append({
                     "id": method_name,
                     "label": label,
                     "components": [{
                        "type": "method-form",
                        "method": method_name,
                        "fields": fields,
                        "submit_label": "Execute",
                        "result_display": "json",
                     }],
                  })

               schema = {
                  "$schema": "microservice-gui/1.0",
                  "service": service_name,
                  "layout": "tabs" if len(sections) > 1 else "single",
                  "title": svc.get("name", service_name),
                  "subtitle": svc.get("description", svc.get("shortdesc", "")),
                  "sections": sections,
               }
               return {"status": "ok", "schema": schema, "source": "auto"}

         return {"status": "ok", "schema": None, "source": "none"}

      # ---- Fleet proxy endpoints ----

      class FleetConfigBody(BaseModel):
         fleet_api_url: str

      class ProcessActionBody(BaseModel):
         process_list: List[str]
         panel_id: str = "fleet"
         force: bool = False

      class FleetCommandBody(BaseModel):
         hub_id: str
         action: str
         params: Optional[dict] = {}

      def _fleet_proxy(method, path, json_body=None):
         """
Forward a request to the FleetWebAPI.

**Arguments:**

* ``method``

  / *Condition*: required / *Type*: str /

  HTTP method ('GET' or 'POST').

* ``path``

  / *Condition*: required / *Type*: str /

  API path to forward to.

* ``json_body``

  / *Condition*: optional / *Type*: dict /

  JSON body for POST requests.
         """
         import httpx

         if not bridge._fleet_api_url:
            from fastapi.responses import JSONResponse
            return JSONResponse(
               status_code=503,
               content={"error": "Fleet API URL not configured"},
            )
         url = bridge._fleet_api_url.rstrip("/") + path
         try:
            with httpx.Client(timeout=10.0) as client:
               if method == "GET":
                  resp = client.get(url)
               else:
                  resp = client.post(url, json=json_body)
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=resp.status_code, content=resp.json())
         except Exception as exc:
            logger.error("Fleet proxy error (%s %s): %s", method, path, exc)
            from fastapi.responses import JSONResponse
            return JSONResponse(
               status_code=502,
               content={"error": "Fleet API unreachable: " + str(exc)},
            )

      @app.get("/api/fleet/config")
      def get_fleet_config():
         return {"fleet_api_url": bridge._fleet_api_url}

      @app.post("/api/fleet/config")
      def set_fleet_config(body: FleetConfigBody):
         bridge._fleet_api_url = body.fleet_api_url or None
         logger.info("Fleet API URL set to %s", bridge._fleet_api_url)
         return {"fleet_api_url": bridge._fleet_api_url}

      @app.get("/api/fleet/status")
      def fleet_status():
         return _fleet_proxy("GET", "/api/fleet/status")

      @app.get("/api/fleet/hubs")
      def fleet_hubs():
         return _fleet_proxy("GET", "/api/fleet/hubs")

      @app.get("/api/fleet/hubs/{hub_id}")
      def fleet_hub_detail(hub_id: str):
         return _fleet_proxy("GET", "/api/fleet/hubs/" + hub_id)

      @app.post("/api/fleet/hubs/{hub_id}/start")
      def fleet_hub_start(hub_id: str, body: ProcessActionBody):
         return _fleet_proxy("POST", "/api/fleet/hubs/" + hub_id + "/start",
                             body.model_dump())

      @app.post("/api/fleet/hubs/{hub_id}/stop")
      def fleet_hub_stop(hub_id: str, body: ProcessActionBody):
         return _fleet_proxy("POST", "/api/fleet/hubs/" + hub_id + "/stop",
                             body.model_dump())

      @app.post("/api/fleet/hubs/{hub_id}/reset")
      def fleet_hub_reset(hub_id: str):
         return _fleet_proxy("POST", "/api/fleet/hubs/" + hub_id + "/reset")

      @app.post("/api/fleet/command")
      def fleet_command(body: FleetCommandBody):
         return _fleet_proxy("POST", "/api/fleet/command", body.model_dump())

      # ---- Local Hub endpoints ----

      class LocalHubStartBody(BaseModel):
         mode: str = "standalone"
         xpub_port: int = 5555
         xsub_port: int = 5556
         orchestrator_url: str = ""
         hub_id: str = ""
         hub_name: str = ""
         process_config: Optional[dict] = None
         fleet_api_port: int = 2510
         health_timeout: float = 30.0

      class LocalHubProcessActionBody(BaseModel):
         names: List[str]
         force: bool = False

      class LocalHubConfigBody(BaseModel):
         name: str = ""
         config: dict = {}

      def _get_local_hub_manager():
         if bridge._local_hub_manager is None:
            hub_type = os.environ.get('DASGUI_HUB_TYPE', 'local')

            if hub_type == 'nomad':
               from ..nomad_hub.nomad_hub_adapter import NomadHubAdapter
               nomad_addr = os.environ.get(
                  'NOMAD_ADDR', 'http://127.0.0.1:4646')
               nomad_token = os.environ.get('NOMAD_TOKEN', '')
               nomad_namespace = os.environ.get(
                  'NOMAD_NAMESPACE', 'default')
               nomad_dc = os.environ.get('NOMAD_DC', 'dc1')
               bridge._local_hub_manager = NomadHubAdapter(
                  address=nomad_addr, token=nomad_token,
                  namespace=nomad_namespace, datacenter=nomad_dc,
                  on_status_change=lambda s: bridge.broadcast_update(s),
               )
               logger.info('Hub backend: Nomad (%s)', nomad_addr)
            else:
               from ..local_hub.local_hub_manager import LocalHubManager
               # Prefer env var (set by launcher.py for packaged apps),
               # fall back to relative path for development mode.
               hub_config_path = os.environ.get('DASGUI_HUB_CONFIG')
               if not hub_config_path:
                  hub_config_path = os.path.join(
                     os.path.dirname(__file__), '..', '..',
                     'MicroserviceManagerGUI', 'python',
                     'hub_processes.json'
                  )
               bridge._local_hub_manager = LocalHubManager(
                  config_path=hub_config_path
               )
               logger.info('Hub backend: local (%s)', hub_config_path)
         return bridge._local_hub_manager

      @app.post("/api/local-hub/start")
      def local_hub_start(body: LocalHubStartBody):
         mgr = _get_local_hub_manager()
         result = mgr.start_hub(
            mode=body.mode,
            xpub_port=body.xpub_port,
            xsub_port=body.xsub_port,
            orchestrator_url=body.orchestrator_url,
            hub_id=body.hub_id,
            hub_name=body.hub_name,
            process_config=body.process_config,
            fleet_api_port=body.fleet_api_port,
            health_timeout=body.health_timeout,
         )
         # Auto-configure fleet API URL when orchestrator actually started
         if result.get("fleet_api_port"):
            bridge._fleet_api_url = f"http://localhost:{result['fleet_api_port']}"
            logger.info("Fleet API URL auto-set to %s", bridge._fleet_api_url)
         return result

      @app.post("/api/local-hub/stop")
      def local_hub_stop():
         mgr = _get_local_hub_manager()
         result = mgr.stop_hub()
         # Orchestrator is part of the hub — clear fleet URL so the proxy
         # returns 503 and the GUI auto-disconnects from the fleet.
         if bridge._fleet_api_url:
            logger.info("Clearing fleet API URL (hub stopped)")
            bridge._fleet_api_url = None
         return result

      @app.get("/api/local-hub/status")
      def local_hub_status():
         mgr = _get_local_hub_manager()
         return mgr.get_status()

      @app.post("/api/local-hub/processes/start")
      def local_hub_processes_start(body: LocalHubProcessActionBody):
         mgr = _get_local_hub_manager()
         return mgr.start_processes(body.names)

      @app.post("/api/local-hub/processes/stop")
      def local_hub_processes_stop(body: LocalHubProcessActionBody):
         mgr = _get_local_hub_manager()
         return mgr.stop_processes(body.names, force=body.force)

      @app.get("/api/local-hub/config")
      def local_hub_config_get():
         mgr = _get_local_hub_manager()
         return mgr.get_config()

      @app.post("/api/local-hub/config")
      def local_hub_config_add(body: LocalHubConfigBody):
         mgr = _get_local_hub_manager()
         return mgr.add_config(body.name, body.config)

      @app.put("/api/local-hub/config/{name}")
      def local_hub_config_update(name: str, body: LocalHubConfigBody):
         mgr = _get_local_hub_manager()
         return mgr.update_config(name, body.config)

      @app.delete("/api/local-hub/config/{name}")
      def local_hub_config_delete(name: str):
         mgr = _get_local_hub_manager()
         return mgr.remove_config(name)

      @app.post("/api/local-hub/reset")
      def local_hub_reset():
         mgr = _get_local_hub_manager()
         return mgr.reset()

      class ImportServiceBody(BaseModel):
         name: str
         source_path: str = ""
         zip_data: str = ""
         wait_time: float = 1.0

      @app.delete("/api/local-hub/service/{name}")
      def local_hub_remove_service(name: str):
         mgr = _get_local_hub_manager()
         return mgr.remove_service(name)

      @app.get("/api/local-hub/service/{name}/log")
      def local_hub_service_log(name: str, tail: int = 100):
         mgr = _get_local_hub_manager()
         return mgr.get_service_log(name, tail=tail)

      @app.post("/api/local-hub/import-service")
      def local_hub_import_service(body: ImportServiceBody):
         mgr = _get_local_hub_manager()
         return mgr.import_service(
            name=body.name,
            source_path=body.source_path,
            zip_data=body.zip_data,
            wait_time=body.wait_time,
         )

      # ---- Nomad agent management & proxy endpoints ----

      class NomadConfigBody(BaseModel):
         nomad_url: str = ""

      class NomadAgentStartBody(BaseModel):
         mode: str = "dev"              # "dev" or "config"
         bind_addr: str = "0.0.0.0"
         http_port: int = 4646
         datacenter: str = "dc1"
         node_name: str = ""
         config_file: str = ""          # path to .hcl config file
         data_dir: str = ""             # data directory
         nomad_path: str = "nomad"      # path to nomad binary
         extra_args: list = []

      # ---- Agent PID file management (survives bridge restarts) ----
      #
      # Same pattern as Electron's bridge PID file: write a PID when we
      # spawn an agent, read it back to detect still-running agents
      # after a bridge restart, kill by PID when stopping.

      def _agent_pid_path(name: str) -> str:
         """Return the path to the PID file for a managed agent."""
         import tempfile
         return os.path.join(tempfile.gettempdir(), f'msbase_{name}_agent.pid')

      def _save_agent_pid(name: str, pid: int, url: str = ''):
         """Write PID + URL to a file so we can find the agent after restart."""
         try:
            with open(_agent_pid_path(name), 'w') as f:
               f.write(f'{pid}\n{url}\n')
         except Exception:
            pass

      def _load_agent_pid(name: str):
         """Read saved PID + URL.  Returns (pid, url) or (None, None)."""
         try:
            with open(_agent_pid_path(name), 'r') as f:
               lines = f.read().strip().split('\n')
               pid = int(lines[0]) if lines else None
               url = lines[1].strip() if len(lines) > 1 else ''
               return pid, url
         except Exception:
            return None, None

      def _remove_agent_pid(name: str):
         try:
            os.remove(_agent_pid_path(name))
         except Exception:
            pass

      def _is_pid_alive(pid: int) -> bool:
         """Check if a process with the given PID is still running."""
         if pid is None:
            return False
         try:
            import psutil
            return psutil.pid_exists(pid)
         except ImportError:
            # Fallback without psutil
            try:
               os.kill(pid, 0)
               return True
            except (OSError, ProcessLookupError):
               return False

      def _kill_pid(pid: int) -> bool:
         """Kill a process by PID.  Returns True if successfully killed."""
         if pid is None:
            return False
         try:
            import psutil
            proc = psutil.Process(pid)
            proc.terminate()
            try:
               proc.wait(timeout=10)
            except psutil.TimeoutExpired:
               proc.kill()
            return True
         except Exception:
            # Fallback
            try:
               import signal
               os.kill(pid, signal.SIGTERM)
               return True
            except Exception:
               return False

      def _get_nomad_agent():
         """Get the managed Nomad agent subprocess info."""
         if not hasattr(bridge, '_nomad_agent_proc'):
            bridge._nomad_agent_proc = None
            bridge._nomad_agent_log = []
         return bridge._nomad_agent_proc

      @app.post("/api/nomad/agent/start")
      def nomad_agent_start(body: NomadAgentStartBody):
         import subprocess, shutil, threading, socket

         # Check if already running
         proc = _get_nomad_agent()
         if proc and proc.poll() is None:
            return {"success": False,
                    "message": "Nomad agent already running (PID %d)" % proc.pid,
                    "pid": proc.pid}

         # Pre-check: is the HTTP port already taken?
         def _probe(host: str, port: int) -> bool:
            probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            try:
               return s.connect_ex((probe_host, port)) == 0
            except Exception:
               return False
            finally:
               s.close()

         if _probe("127.0.0.1", body.http_port):
            return {"success": False,
                    "message": (
                        "Port %d is already in use. "
                        "Either stop the process currently using it, or "
                        "choose a different HTTP port in the Advanced section."
                    ) % body.http_port}

         # Find nomad binary
         nomad_bin = body.nomad_path or 'nomad'
         resolved = shutil.which(nomad_bin)
         if not resolved:
            return {"success": False,
                    "message": "Nomad binary not found: '%s'. "
                               "Install from https://developer.hashicorp.com/nomad/install" % nomad_bin}

         # Build command
         args = [resolved, 'agent']
         if body.mode == 'dev':
            args.append('-dev')
            if body.bind_addr and body.bind_addr != '127.0.0.1':
               args.extend(['-bind', body.bind_addr])
            if body.node_name:
               args.extend(['-node', body.node_name])
            if body.datacenter != 'dc1':
               args.extend(['-dc', body.datacenter])
         else:
            # Config mode
            if body.config_file:
               args.extend(['-config', body.config_file])
            if body.data_dir:
               args.extend(['-data-dir', body.data_dir])
            if body.bind_addr:
               args.extend(['-bind', body.bind_addr])
            if body.node_name:
               args.extend(['-node', body.node_name])
            if body.datacenter != 'dc1':
               args.extend(['-dc', body.datacenter])

         for arg in (body.extra_args or []):
            args.append(str(arg))

         logger.info('Starting Nomad agent: %s', ' '.join(args))
         bridge._nomad_agent_log = []

         try:
            proc = subprocess.Popen(
               args,
               stdout=subprocess.PIPE,
               stderr=subprocess.STDOUT,
               text=True,
               bufsize=1,
            )
         except Exception as e:
            return {"success": False, "message": "Failed to start: %s" % e}

         bridge._nomad_agent_proc = proc
         nomad_url = 'http://127.0.0.1:%d' % body.http_port
         _save_agent_pid('nomad', proc.pid, nomad_url)

         # Background thread to capture log output
         def _read_output():
            max_lines = 500
            try:
               for line in proc.stdout:
                  line = line.rstrip('\n')
                  bridge._nomad_agent_log.append(line)
                  if len(bridge._nomad_agent_log) > max_lines:
                     bridge._nomad_agent_log = bridge._nomad_agent_log[-max_lines:]
            except Exception:
               pass

         t = threading.Thread(target=_read_output, daemon=True,
                              name='nomad-agent-log')
         t.start()

         # Auto-configure client after brief startup delay
         import time
         nomad_url = 'http://127.0.0.1:%d' % body.http_port

         def _auto_configure():
            time.sleep(2)
            _ensure_nomad(nomad_url)

         threading.Thread(target=_auto_configure, daemon=True).start()

         return {"success": True, "pid": proc.pid,
                 "message": "Nomad agent started (PID %d)" % proc.pid,
                 "nomad_url": nomad_url}

      @app.post("/api/nomad/agent/stop")
      def nomad_agent_stop():
         proc = _get_nomad_agent()

         # Try subprocess handle first (same-session agent).
         if proc and proc.poll() is None:
            pid = proc.pid
            logger.info('Stopping Nomad agent via handle (PID %d)', pid)
            try:
               proc.terminate()
               try:
                  proc.wait(timeout=10)
               except Exception:
                  proc.kill()
            except Exception as e:
               return {"success": False,
                       "message": "Failed to stop PID %d: %s" % (pid, e)}
            bridge._nomad_agent_proc = None
            _remove_agent_pid('nomad')
            return {"success": True,
                    "message": "Nomad agent stopped (PID %d)" % pid}

         bridge._nomad_agent_proc = None

         # Handle lost (bridge restarted) — try saved PID file.
         saved_pid, _ = _load_agent_pid('nomad')
         if saved_pid and _is_pid_alive(saved_pid):
            logger.info('Stopping Nomad agent via saved PID %d', saved_pid)
            if _kill_pid(saved_pid):
               _remove_agent_pid('nomad')
               return {"success": True,
                       "message": "Nomad agent stopped (PID %d)" % saved_pid}
            else:
               return {"success": False,
                       "message": "Failed to kill PID %d" % saved_pid}

         _remove_agent_pid('nomad')
         return {"success": True, "message": "Nomad agent not running"}

      @app.get("/api/nomad/agent/status")
      def nomad_agent_status():
         proc = _get_nomad_agent()
         running = proc is not None and proc.poll() is None
         pid = proc.pid if running else None
         nomad_url = getattr(bridge, '_nomad_url', None)

         # After a bridge restart the subprocess handle is lost.
         # Check the saved PID file to find the still-running agent.
         if not running:
            saved_pid, saved_url = _load_agent_pid('nomad')
            if saved_pid and _is_pid_alive(saved_pid):
               running = True
               pid = saved_pid
               if saved_url:
                  nomad_url = saved_url
                  bridge._nomad_url = saved_url
            else:
               # PID file is stale — clean it up.
               _remove_agent_pid('nomad')

         return {
            "running": running,
            "pid": pid,
            "nomad_url": nomad_url,
         }

      @app.get("/api/nomad/agent/log")
      def nomad_agent_log(tail: int = 100):
         logs = getattr(bridge, '_nomad_agent_log', [])
         lines = logs[-tail:] if len(logs) > tail else logs
         return {"log": '\n'.join(lines)}

      def _get_nomad_client():
         """Lazy-create a NomadClient for proxy endpoints."""
         if not hasattr(bridge, '_nomad_client'):
            bridge._nomad_client = None
            bridge._nomad_url = None
         return bridge._nomad_client

      def _ensure_nomad(url=None):
         if url and url != getattr(bridge, '_nomad_url', None):
            from ..nomad_hub.nomad_client import NomadClient
            bridge._nomad_client = NomadClient(
               address=url,
               token=os.environ.get('NOMAD_TOKEN', ''),
               namespace=os.environ.get('NOMAD_NAMESPACE', 'default'),
            )
            bridge._nomad_url = url
            logger.info('Nomad client configured: %s', url)
         return getattr(bridge, '_nomad_client', None)

      @app.post("/api/nomad/config")
      def nomad_config_set(body: NomadConfigBody):
         url = body.nomad_url or ''
         if url:
            _ensure_nomad(url)
            return {"nomad_url": url, "status": "configured"}
         bridge._nomad_client = None
         bridge._nomad_url = None
         return {"nomad_url": "", "status": "cleared"}

      @app.get("/api/nomad/health")
      def nomad_health():
         """Return ``{ok, ...}`` to match the shape of /api/consul/health.

         The infra status pills in the GUI check ``data.ok``; returning
         ``status`` alone (as an older version did) caused the LED to
         always show red even when Nomad was healthy.
         """
         nc = _get_nomad_client()
         if not nc:
            # Auto-configure from env or default so the first GUI load
            # after a fresh bridge start can still detect a running agent.
            url = os.environ.get('NOMAD_ADDR', 'http://127.0.0.1:4646')
            nc = _ensure_nomad(url)
         if not nc:
            return {"ok": False, "error": "not configured",
                    "nomad_url": getattr(bridge, '_nomad_url', None)}
         try:
            info = nc.agent_self()
            member = info.get('member', {}) or {}
            config = info.get('config', {}) or {}
            return {
               "ok": True,
               "server": member.get('Name', ''),
               "version": config.get('Version', '') or
                          (info.get('stats', {}) or {}).get('client', {}).get('node_id', ''),
               "nomad_url": getattr(bridge, '_nomad_url', None),
            }
         except Exception as e:
            return {"ok": False, "error": str(e),
                    "nomad_url": getattr(bridge, '_nomad_url', None)}

      @app.get("/api/nomad/discover")
      def nomad_discover():
         """Find running Nomad agents by enumerating local processes.

         Uses :mod:`psutil` to list processes whose name starts with
         ``nomad`` and their listening TCP sockets.  A Nomad agent opens
         three ports (HTTP 4646, RPC 4647, Serf 4648 by default), but only
         the HTTP one responds to ``/v1/agent/self`` — we probe each
         candidate listening port and report the ones that do.

         Returns:
            {"instances": [
                {"url": "...", "host": "...", "port": N, "pid": N,
                 "name": "...", "version": "...", "datacenter": "...",
                 "server": bool, "exe": "..."}, ...
             ]}
         """
         import urllib.request, urllib.error
         try:
            import psutil
         except ImportError:
            return {"instances": [],
                    "error": "psutil not installed on the bridge Python"}

         found: list = []
         seen: set = set()

         for proc in psutil.process_iter(attrs=('pid', 'name', 'exe')):
            try:
               pname = (proc.info.get('name') or '').lower()
               # Match ``nomad`` or ``nomad.exe`` but not ``nomad-client``
               # that's some unrelated binary.  Nomad's own binary is
               # always exactly ``nomad`` / ``nomad.exe``.
               base = pname.rsplit('.', 1)[0]
               if base != 'nomad':
                  continue

               try:
                  conns = proc.net_connections(kind='tcp')
               except (psutil.AccessDenied, psutil.NoSuchProcess):
                  continue

               for c in conns:
                  if c.status != psutil.CONN_LISTEN:
                     continue
                  if not c.laddr:
                     continue
                  ip = c.laddr.ip or '127.0.0.1'
                  port = c.laddr.port
                  # Reach ``0.0.0.0``/``::`` via 127.0.0.1 locally.
                  probe_host = ip if ip not in ("0.0.0.0", "::", "") else "127.0.0.1"
                  key = (probe_host, port)
                  if key in seen:
                     continue
                  seen.add(key)

                  # Only the HTTP port answers /v1/agent/self; RPC and
                  # Serf will fast-reject.  Use a short timeout.
                  url = "http://%s:%d" % (probe_host, port)
                  try:
                     req = urllib.request.Request(url + '/v1/agent/self')
                     with urllib.request.urlopen(req, timeout=1.5) as resp:
                        info = json.loads(resp.read().decode('utf-8'))
                  except Exception:
                     continue

                  member = info.get('member', {}) or {}
                  config = info.get('config', {}) or {}
                  stats  = info.get('stats',  {}) or {}
                  is_server = bool((config.get('Server') or {}).get('Enabled')) \
                              or ('runtime' in stats and 'nomad' in stats)

                  found.append({
                     "url":        url,
                     "host":       probe_host,
                     "port":       port,
                     "pid":        proc.pid,
                     "exe":        proc.info.get('exe') or '',
                     "name":       member.get('Name', ''),
                     "version":    config.get('Version', '') or
                                   member.get('Tags', {}).get('build', ''),
                     "datacenter": (config.get('Datacenter') or
                                    member.get('Tags', {}).get('dc') or ''),
                     "server":     is_server,
                  })

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
               continue
            except Exception:
               # Don't let one bad process break the whole scan.
               continue

         return {"instances": found}

      @app.get("/api/nomad/jobs")
      def nomad_list_jobs():
         nc = _get_nomad_client()
         if not nc:
            return []
         try:
            return nc.list_jobs()
         except Exception as e:
            logger.error('Nomad list jobs: %s', e)
            return []

      @app.get("/api/nomad/jobs/{job_id}")
      def nomad_get_job(job_id: str):
         nc = _get_nomad_client()
         if not nc:
            return {"error": "Nomad not configured"}
         return nc.get_job(job_id)

      @app.get("/api/nomad/jobs/{job_id}/allocations")
      def nomad_get_allocations(job_id: str):
         nc = _get_nomad_client()
         if not nc:
            return []
         return nc.get_allocations(job_id)

      class NomadStopBody(BaseModel):
         purge: bool = False

      @app.post("/api/nomad/jobs/{job_id}/start")
      def nomad_start_job(job_id: str):
         nc = _get_nomad_client()
         if not nc:
            return {"success": False, "message": "Nomad not configured"}
         try:
            # Re-register the job (Nomad restarts stopped jobs on re-register)
            job = nc.get_job(job_id)
            result = nc.register_job(job)
            return {"success": True, "eval_id": result.get("EvalID", "")}
         except Exception as e:
            return {"success": False, "message": str(e)}

      @app.post("/api/nomad/jobs/{job_id}/stop")
      def nomad_stop_job(job_id: str, body: NomadStopBody = None):
         nc = _get_nomad_client()
         if not nc:
            return {"success": False, "message": "Nomad not configured"}
         try:
            purge = body.purge if body else False
            result = nc.stop_job(job_id, purge=purge)
            return {"success": True, "eval_id": result.get("EvalID", "")}
         except Exception as e:
            return {"success": False, "message": str(e)}

      class NomadSubmitJobBody(BaseModel):
         """Payload for POST /api/nomad/jobs/submit.

         The user pastes either raw HCL or a full job JSON (what Nomad's
         /v1/jobs expects, with the top-level ``{"Job": {...}}`` wrapper OR
         just the inner job dict).  Format is selected by ``content_type``.
         """
         content: str = ""
         content_type: str = "hcl"   # "hcl" or "json"
         canonicalize: bool = True

      @app.post("/api/nomad/jobs/submit")
      def nomad_submit_job(body: NomadSubmitJobBody):
         """Parse + register a Nomad job from HCL or JSON.

         On success returns the EvalID (same as ``nomad job run``).  On
         failure returns ``{success: false, stage: "parse"|"register",
         message: "..."}``.
         """
         nc = _get_nomad_client()
         if not nc:
            return {"success": False, "stage": "client",
                    "message": "Nomad not configured. Start an agent first."}

         if not body.content.strip():
            return {"success": False, "stage": "input",
                    "message": "Empty job content."}

         # -- Step 1: obtain a job dict -------------------------------------
         job_spec = None
         try:
            if body.content_type.lower() == "hcl":
               job_spec = nc.parse_hcl(body.content,
                                       canonicalize=body.canonicalize)
            else:
               parsed = json.loads(body.content)
               # Accept both {"Job": {...}} and the bare job dict.
               if isinstance(parsed, dict) and "Job" in parsed:
                  job_spec = parsed["Job"]
               else:
                  job_spec = parsed
         except Exception as e:
            return {"success": False, "stage": "parse",
                    "message": f"Failed to parse job: {e}"}

         if not isinstance(job_spec, dict):
            return {"success": False, "stage": "parse",
                    "message": "Parsed job is not an object."}

         # -- Step 2: register ----------------------------------------------
         try:
            result = nc.register_job(job_spec)
            return {"success": True,
                    "job_id": job_spec.get("ID") or job_spec.get("Name") or "",
                    "eval_id": result.get("EvalID", ""),
                    "warnings": result.get("Warnings", "")}
         except Exception as e:
            return {"success": False, "stage": "register",
                    "message": f"Failed to register job: {e}"}

      @app.get("/api/nomad/jobs/{job_id}/logs")
      def nomad_get_logs(job_id: str, type: str = "stdout"):
         nc = _get_nomad_client()
         if not nc:
            return {"name": job_id, "log": "(Nomad not configured)"}
         try:
            allocs = nc.get_allocations(job_id)
            if not allocs:
               return {"name": job_id, "log": "(no allocations)"}
            latest = sorted(allocs,
                            key=lambda a: a.get('CreateIndex', 0),
                            reverse=True)[0]
            alloc_id = latest['ID']
            task_states = latest.get('TaskStates') or {}
            task_name = next(iter(task_states), None)
            if not task_name:
               return {"name": job_id, "log": "(no task found)"}
            log_text = nc.get_logs(alloc_id, task_name, log_type=type)
            return {"name": job_id, "log": log_text,
                    "alloc_id": alloc_id, "task": task_name}
         except Exception as e:
            return {"name": job_id, "log": f"(error: {e})"}

      # =====================================================================
      # Consul agent management & service discovery
      # =====================================================================
      #
      # Mirror of the Nomad agent endpoints above.  Consul is the service
      # registry used by the new gRPC-based runtime; services register
      # themselves on startup and the GUI discovers them via these endpoints.

      class ConsulAgentStartBody(BaseModel):
         mode: str = "dev"               # "dev" or "config"
         bind_addr: str = "0.0.0.0"
         http_port: int = 8500
         datacenter: str = "dc1"
         node_name: str = ""
         config_dir: str = ""            # path to config directory (.hcl/.json)
         data_dir: str = ""              # data directory
         consul_path: str = "consul"     # path to consul binary
         extra_args: list = []

      def _get_consul_agent():
         """Get the managed Consul agent subprocess info."""
         if not hasattr(bridge, '_consul_agent_proc'):
            bridge._consul_agent_proc = None
            bridge._consul_agent_log = []
         return bridge._consul_agent_proc

      def _port_in_use(host: str, port: int) -> bool:
         """Return True if TCP ``port`` on ``host`` is already listening.

         Used to pre-check Consul/Nomad HTTP ports so we can return a clear
         error message instead of spawning an agent that dies immediately.
         """
         import socket
         probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
         s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
         s.settimeout(0.3)
         try:
            result = s.connect_ex((probe_host, port))
            return result == 0  # 0 => port accepted the connection
         except Exception:
            return False
         finally:
            s.close()

      @app.post("/api/consul/agent/start")
      def consul_agent_start(body: ConsulAgentStartBody):
         import subprocess, shutil, threading, time

         proc = _get_consul_agent()
         if proc and proc.poll() is None:
            return {"success": False,
                    "message": "Consul agent already running (PID %d)" % proc.pid,
                    "pid": proc.pid}

         # Pre-check: is the HTTP port already taken by *something*?
         if _port_in_use("127.0.0.1", body.http_port):
            return {"success": False,
                    "message": (
                        "Port %d is already in use. "
                        "Either stop the process currently using it, or "
                        "choose a different HTTP port in the Advanced section."
                    ) % body.http_port}

         consul_bin = body.consul_path or 'consul'
         resolved = shutil.which(consul_bin)
         if not resolved:
            return {"success": False,
                    "message": "Consul binary not found: '%s'. "
                               "Install from https://developer.hashicorp.com/consul/install" % consul_bin}

         args = [resolved, 'agent']
         if body.mode == 'dev':
            args.append('-dev')
            if body.bind_addr and body.bind_addr != '127.0.0.1':
               args.extend(['-bind', body.bind_addr])
            if body.node_name:
               args.extend(['-node', body.node_name])
            if body.datacenter != 'dc1':
               args.extend(['-datacenter', body.datacenter])
            if body.http_port != 8500:
               args.extend(['-http-port', str(body.http_port)])
         else:
            # Config mode — expects a directory containing .hcl/.json files.
            if body.config_dir:
               args.extend(['-config-dir', body.config_dir])
            if body.data_dir:
               args.extend(['-data-dir', body.data_dir])
            if body.bind_addr:
               args.extend(['-bind', body.bind_addr])
            if body.node_name:
               args.extend(['-node', body.node_name])
            if body.datacenter != 'dc1':
               args.extend(['-datacenter', body.datacenter])
            if body.http_port != 8500:
               args.extend(['-http-port', str(body.http_port)])

         for arg in (body.extra_args or []):
            args.append(str(arg))

         logger.info('Starting Consul agent: %s', ' '.join(args))
         bridge._consul_agent_log = []

         try:
            proc = subprocess.Popen(
               args,
               stdout=subprocess.PIPE,
               stderr=subprocess.STDOUT,
               text=True,
               bufsize=1,
            )
         except Exception as e:
            return {"success": False, "message": "Failed to start: %s" % e}

         bridge._consul_agent_proc = proc
         consul_url_val = 'http://127.0.0.1:%d' % body.http_port
         _save_agent_pid('consul', proc.pid, consul_url_val)

         def _read_output():
            max_lines = 500
            try:
               for line in proc.stdout:
                  line = line.rstrip('\n')
                  bridge._consul_agent_log.append(line)
                  if len(bridge._consul_agent_log) > max_lines:
                     bridge._consul_agent_log = bridge._consul_agent_log[-max_lines:]
            except Exception:
               pass

         threading.Thread(target=_read_output, daemon=True,
                          name='consul-agent-log').start()

         # Give the agent a moment to either bind the port or fail.  If it
         # already exited, surface the captured log tail as the error — much
         # friendlier than letting the GUI retry for 12 seconds.
         time.sleep(1.0)
         if proc.poll() is not None:
            bridge._consul_agent_proc = None
            log_tail = '\n'.join(bridge._consul_agent_log[-15:])
            return {"success": False,
                    "message": (
                        "Consul agent exited immediately (code %d). "
                        "Last log lines:\n%s"
                    ) % (proc.returncode, log_tail or "(no output)"),
                    "log": log_tail}

         consul_url = 'http://127.0.0.1:%d' % body.http_port
         bridge._consul_url = consul_url

         return {"success": True, "pid": proc.pid,
                 "message": "Consul agent started (PID %d)" % proc.pid,
                 "consul_url": consul_url}

      @app.post("/api/consul/agent/stop")
      def consul_agent_stop():
         proc = _get_consul_agent()

         if proc and proc.poll() is None:
            pid = proc.pid
            logger.info('Stopping Consul agent via handle (PID %d)', pid)
            try:
               proc.terminate()
               try:
                  proc.wait(timeout=10)
               except Exception:
                  proc.kill()
            except Exception as e:
               return {"success": False,
                       "message": "Failed to stop PID %d: %s" % (pid, e)}
            bridge._consul_agent_proc = None
            _remove_agent_pid('consul')
            return {"success": True,
                    "message": "Consul agent stopped (PID %d)" % pid}

         bridge._consul_agent_proc = None

         saved_pid, _ = _load_agent_pid('consul')
         if saved_pid and _is_pid_alive(saved_pid):
            logger.info('Stopping Consul agent via saved PID %d', saved_pid)
            if _kill_pid(saved_pid):
               _remove_agent_pid('consul')
               return {"success": True,
                       "message": "Consul agent stopped (PID %d)" % saved_pid}
            else:
               return {"success": False,
                       "message": "Failed to kill PID %d" % saved_pid}

         _remove_agent_pid('consul')
         return {"success": True, "message": "Consul agent not running"}

      @app.get("/api/consul/agent/status")
      def consul_agent_status():
         proc = _get_consul_agent()
         running = proc is not None and proc.poll() is None
         pid = proc.pid if running else None
         consul_url = getattr(bridge, '_consul_url', None)

         if not running:
            saved_pid, saved_url = _load_agent_pid('consul')
            if saved_pid and _is_pid_alive(saved_pid):
               running = True
               pid = saved_pid
               if saved_url:
                  consul_url = saved_url
                  bridge._consul_url = saved_url
            else:
               _remove_agent_pid('consul')

         return {
            "running": running,
            "pid": pid,
            "consul_url": consul_url,
         }

      @app.get("/api/consul/agent/log")
      def consul_agent_log(tail: int = 100):
         logs = getattr(bridge, '_consul_agent_log', [])
         lines = logs[-tail:] if len(logs) > tail else logs
         return {"log": '\n'.join(lines)}

      # ---- Consul HTTP API proxy ----
      #
      # Simple pass-through so the browser does not need CORS handling.
      # Uses urllib (stdlib) to avoid a new dependency.

      def _consul_url():
         return getattr(bridge, '_consul_url', None) or 'http://127.0.0.1:8500'

      class ConsulConfigBody(BaseModel):
         consul_url: str = ""

      @app.post("/api/consul/config")
      def consul_config(body: ConsulConfigBody):
         """Set the bridge-side Consul HTTP URL.

         Used by the GUI to restore its configured Consul endpoint after a
         bridge restart (the URL is kept in memory only, so it's lost on
         kill).  Passing an empty string resets to the default.
         """
         if body.consul_url:
            bridge._consul_url = body.consul_url.rstrip('/')
         else:
            if hasattr(bridge, '_consul_url'):
               delattr(bridge, '_consul_url')
         return {"ok": True, "consul_url": _consul_url()}

      def _resolve_consul_url(override: str = "") -> str:
         """Return the Consul base URL to use.

         If *override* is provided (from a ``?consul=...`` query param) it
         wins.  Otherwise fall back to the bridge's in-memory default.
         """
         if override:
            return override.rstrip('/')
         return _consul_url().rstrip('/')

      def _consul_get(path: str, consul: str = ""):
         """Proxy GET to a Consul HTTP API path.

         Every /api/consul/* endpoint accepts an optional ``consul`` query
         param so the GUI can talk to multiple Consul clusters at once
         without the bridge holding state for each one.
         """
         import urllib.request, urllib.error
         url = _resolve_consul_url(consul) + path
         try:
            with urllib.request.urlopen(url, timeout=5) as resp:
               body = resp.read().decode('utf-8')
               return json.loads(body) if body else None
         except urllib.error.URLError as e:
            return {"_error": str(e)}
         except Exception as e:
            return {"_error": str(e)}

      @app.get("/api/consul/health")
      def consul_health(consul: str = ""):
         """Probe Consul by calling /v1/status/leader."""
         import urllib.request, urllib.error
         base = _resolve_consul_url(consul)
         url = base + '/v1/status/leader'
         try:
            with urllib.request.urlopen(url, timeout=3) as resp:
               leader = resp.read().decode('utf-8').strip('"')
               return {"ok": True, "leader": leader, "consul_url": base}
         except Exception as e:
            return {"ok": False, "error": str(e), "consul_url": base}

      @app.get("/api/consul/services")
      def consul_services(consul: str = ""):
         """List all services registered in Consul.  Returns the raw
         {service_name: [tags...]} map from /v1/catalog/services."""
         data = _consul_get('/v1/catalog/services', consul=consul)
         return data or {}

      @app.get("/api/consul/services/{name}")
      def consul_service_detail(name: str, consul: str = "", passing: bool = False):
         """Return instances of a service.

         When ``passing=true`` is passed, Consul filters to only healthy
         instances.  Default is now ``false`` so the GUI can read the
         Checks array and compute a per-service status (green/yellow/red)
         for the sidebar indicator.
         """
         path = '/v1/health/service/%s' % name
         if passing:
            path += '?passing=true'
         data = _consul_get(path, consul=consul)
         return data or []

      @app.get("/api/consul/nodes")
      def consul_nodes(consul: str = ""):
         data = _consul_get('/v1/catalog/nodes', consul=consul)
         return data or []

      @app.get("/api/consul/discover")
      def consul_discover():
         """Find running Consul agents by enumerating local processes.

         Uses :mod:`psutil` to find processes whose name is exactly
         ``consul`` and probes each of their listening TCP ports with
         ``GET /v1/status/leader`` — only the HTTP API port answers,
         the Serf/RPC/DNS ports fast-reject.

         Returns:
            {"instances": [
                {"url": "...", "host": "...", "port": N, "pid": N,
                 "leader": "...", "datacenter": "...", "server": bool,
                 "version": "...", "node_name": "..."}, ...
             ]}
         """
         import urllib.request, urllib.error
         try:
            import psutil
         except ImportError:
            return {"instances": [],
                    "error": "psutil not installed on the bridge Python"}

         found: list = []
         seen: set = set()

         for proc in psutil.process_iter(attrs=('pid', 'name', 'exe')):
            try:
               pname = (proc.info.get('name') or '').lower()
               base = pname.rsplit('.', 1)[0]
               if base != 'consul':
                  continue

               try:
                  conns = proc.net_connections(kind='tcp')
               except (psutil.AccessDenied, psutil.NoSuchProcess):
                  continue

               for c in conns:
                  if c.status != psutil.CONN_LISTEN:
                     continue
                  if not c.laddr:
                     continue
                  ip = c.laddr.ip or '127.0.0.1'
                  port = c.laddr.port
                  probe_host = ip if ip not in ("0.0.0.0", "::", "") else "127.0.0.1"
                  key = (probe_host, port)
                  if key in seen:
                     continue
                  seen.add(key)

                  url = "http://%s:%d" % (probe_host, port)
                  leader = None
                  try:
                     req = urllib.request.Request(url + '/v1/status/leader')
                     with urllib.request.urlopen(req, timeout=1.0) as resp:
                        leader = resp.read().decode('utf-8').strip('"')
                  except Exception:
                     continue

                  # Supplementary agent info (version, datacenter, node,
                  # server mode) — if /v1/agent/self fails we still keep
                  # the instance because /v1/status/leader already proved
                  # it's Consul HTTP.
                  meta = {}
                  try:
                     req2 = urllib.request.Request(url + '/v1/agent/self')
                     with urllib.request.urlopen(req2, timeout=1.5) as resp2:
                        info = json.loads(resp2.read().decode('utf-8'))
                     cfg = info.get('Config') or info.get('config') or {}
                     meta = {
                        "version":    cfg.get('Version') or cfg.get('version') or '',
                        "datacenter": cfg.get('Datacenter') or cfg.get('datacenter') or '',
                        "node_name":  cfg.get('NodeName') or cfg.get('nodeName') or '',
                        "server":     bool(cfg.get('Server') or cfg.get('server') or False),
                     }
                  except Exception:
                     meta = {"version": "", "datacenter": "",
                             "node_name": "", "server": False}

                  found.append({
                     "url":        url,
                     "host":       probe_host,
                     "port":       port,
                     "pid":        proc.pid,
                     "exe":        proc.info.get('exe') or '',
                     "leader":     leader or '',
                     **meta,
                  })

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
               continue
            except Exception:
               continue

         return {"instances": found}

      # =====================================================================
      # Dynamic gRPC method discovery and invocation
      # =====================================================================
      #
      # The GUI needs to list the methods of any gRPC service registered in
      # Consul and call them, without knowing the proto ahead of time.  We
      # do this via the gRPC server-reflection protocol, which
      # ServiceRunner enables automatically for every MicroserviceBase
      # service.

      def _find_service_target(consul_name: str, consul: str = ""):
         """Look up a service in Consul and return its (host, port, meta) or None."""
         data = _consul_get('/v1/health/service/%s?passing=true' % consul_name,
                            consul=consul)
         if not data or not isinstance(data, list) or len(data) == 0:
            return None
         svc = (data[0] or {}).get('Service', {}) or {}
         host = svc.get('Address') or '127.0.0.1'
         port = svc.get('Port') or 0
         meta = svc.get('Meta') or {}
         return host, port, meta

      def _proto_search_paths(extra: list = None) -> list:
         """Resolve the search paths used to find .proto files when the
         server doesn't ship reflection.  Order: caller-supplied *extra*
         paths first (highest priority — typically a user-typed override
         from the GUI), then ``MB_PROTO_SEARCH_PATH`` env var
         (semicolon-separated), then a few sensible defaults."""
         import os
         paths = []
         for p in (extra or []):
            p = (p or "").strip()
            if p and p not in paths:
               paths.append(p)
         raw = os.environ.get("MB_PROTO_SEARCH_PATH", "")
         for p in raw.split(os.pathsep):
            p = (p or "").strip()
            if p and p not in paths:
               paths.append(p)
         # Sensible defaults — common locations for generated scaffolds.
         here = os.path.dirname(os.path.abspath(__file__))
         repo_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
         for default in [
            os.path.join(repo_root, "examples"),
            os.path.join(repo_root, "SampleServices"),
         ]:
            if os.path.isdir(default) and default not in paths:
               paths.append(default)
         return paths

      def _open_grpc_client(target: str, consul_name: str = "",
                             proto_path: str = ""):
         """Try server reflection first; on UNIMPLEMENTED, fall back to
         compiling local .proto files.

         *proto_path*: optional caller-supplied search dir (e.g. typed
         into the GUI).  Joined with ``MB_PROTO_SEARCH_PATH`` + defaults.

         Returns ``(client, source)`` where ``source`` is one of:
            * ``"reflection"``           — server-side reflection worked
            * ``"local_proto:<paths>"``  — compiled from disk
         Raises :class:`GrpcReflectError` if both paths fail.
         """
         from ..grpc_bridge import (
            GrpcReflectClient, GrpcReflectError, LocalProtoClient,
         )
         import logging as _lg

         # Probe reflection with a cheap list_services() so we detect
         # UNIMPLEMENTED before the caller commits to a specific service.
         client = GrpcReflectClient(target)
         try:
            client.list_services()
            return client, "reflection"
         except GrpcReflectError as exc:
            if not exc.is_unimplemented:
               client.close()
               raise
            client.close()
            _lg.getLogger(__name__).info(
               "Reflection UNIMPLEMENTED on %s; falling back to local proto files",
               target,
            )

         # Fallback — compile local .protos.  GUI-supplied path wins.
         extra = [proto_path] if proto_path else []
         search_paths = _proto_search_paths(extra=extra)
         try:
            local = LocalProtoClient.from_search_paths(target, search_paths)
            return local, "local_proto:" + os.pathsep.join(search_paths)
         except GrpcReflectError as exc:
            hint = ("Set MB_PROTO_SEARCH_PATH or use the in-GUI proto-path "
                    "field to point at a folder containing your service's "
                    ".proto file, or rebuild the server with "
                    "grpc++_reflection enabled.")
            raise GrpcReflectError(
               "Reflection unavailable on %s and no .proto files matched "
               "in search paths (%s).  %s  Underlying: %s"
               % (target, search_paths or "<empty>", hint, exc)
            ) from exc

      @app.get("/api/grpc/services/{consul_name}")
      def grpc_list_methods(consul_name: str, consul: str = "",
                             proto_path: str = ""):
         """Enumerate gRPC services/methods for a Consul-registered service.

         Returns:
            {
              "target": "host:port",
              "discovery_source": "reflection" | "local_proto:...",
              "grpc_services": [
                {
                  "name": "hello.v1.HelloService",
                  "methods": [
                    {"name": "Greet", "input_type": "...", "output_type": "...",
                     "input_fields": [...], "input_skeleton": {...},
                     "client_streaming": false, "server_streaming": false},
                    ...
                  ]
                }
              ]
            }
         """
         from ..grpc_bridge import GrpcReflectError
         import os

         target_info = _find_service_target(consul_name, consul=consul)
         if target_info is None:
            return {"error": "Service '%s' not found in Consul" % consul_name}

         host, port, meta = target_info
         target = "%s:%d" % (host, port)

         advertised = [s.strip() for s in
                        (meta.get('grpc_services') or '').split(',')
                        if s.strip()]

         try:
            client, source = _open_grpc_client(target, consul_name,
                                                proto_path=proto_path)
         except GrpcReflectError as e:
            return {"target": target, "error": str(e)}

         with client:
            try:
               # If reflection worked, prefer Consul-advertised names.
               # If we fell back to local protos, the local pool is the
               # source of truth — its list_services() is authoritative.
               if source == "reflection" and advertised:
                  service_names = advertised
               else:
                  service_names = client.list_services()
            except GrpcReflectError as e:
               return {"target": target, "discovery_source": source,
                       "error": str(e)}

            out = []
            for name in service_names:
               try:
                  methods = client.list_methods(name)
                  out.append({"name": name, "methods": methods})
               except GrpcReflectError as e:
                  out.append({"name": name, "error": str(e)})

         return {"target": target, "discovery_source": source,
                 "grpc_services": out}

      class GrpcCallBody(BaseModel):
         consul_name: str
         grpc_service: str
         method: str
         args_json: str = "{}"
         consul: str = ""
         proto_path: str = ""   # GUI-supplied proto search dir; used as
                                # an additional search path for the
                                # LocalProtoClient fallback.

      @app.post("/api/grpc/call")
      def grpc_call(body: GrpcCallBody):
         """Invoke a unary gRPC method and return the JSON response."""
         from ..grpc_bridge import GrpcReflectError

         target_info = _find_service_target(body.consul_name, consul=body.consul)
         if target_info is None:
            return {"ok": False,
                    "error": "Service '%s' not found in Consul" % body.consul_name}
         host, port, _ = target_info
         target = "%s:%d" % (host, port)

         try:
            client, source = _open_grpc_client(target, body.consul_name,
                                                proto_path=body.proto_path)
         except GrpcReflectError as e:
            return {"ok": False, "target": target, "error": str(e)}

         try:
            with client:
               envelope = client.call_method(
                   body.grpc_service, body.method, body.args_json or "{}"
               )
            # call_method returns either:
            #   {"streaming": False, "result": <dict>}
            #   {"streaming": True,  "events": [...], "truncated": bool, "error"?: str}
            return {"ok": True, "target": target,
                    "discovery_source": source, **envelope}
         except GrpcReflectError as e:
            return {"ok": False, "target": target,
                    "discovery_source": source, "error": str(e)}
         except Exception as e:
            return {"ok": False, "target": target,
                    "discovery_source": source,
                    "error": "%s: %s" % (type(e).__name__, e)}

      # ---- Service Scaffolding endpoint ----

      class ScaffoldMethodParam(BaseModel):
         name: str = ""
         type: str = "str"
         required: bool = True

      class ScaffoldMethod(BaseModel):
         name: str = ""
         params: List[ScaffoldMethodParam] = []
         return_type: str = ""
         description: str = ""

      class ScaffoldRequest(BaseModel):
         service_name: str
         version: str = "1.0.0"
         description: str = ""
         short_description: str = ""
         group: str = ""
         tag: str = ""
         routing_key: str = ""
         transport: str = "rabbitmq"
         gui_support: bool = False
         gui_mode: str = "schema"          # "schema" | "custom"
         gui_schema: Optional[dict] = None  # gui_schema.json content when gui_mode == "schema"
         methods: List[ScaffoldMethod] = []
         output_path: str = ""
         custom_gui_html: str = ""
         custom_gui_js: str = ""

      def _to_snake_case(name):
         """
Convert PascalCase to snake_case.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  PascalCase string to convert.
         """
         import re
         s1 = re.sub(r'([A-Z])', r'_\1', name)
         return s1.lower().lstrip('_').replace('__', '_')

      def _generate_service_class(body: ScaffoldRequest):
         """
Generate the service class source file content.

**Arguments:**

* ``body``

  / *Condition*: required / *Type*: ScaffoldRequest /

  Scaffold request containing service metadata and methods.
         """
         snake_name = _to_snake_case(body.service_name)
         routing_key = body.routing_key or ('service.' + snake_name)

         lines = []
         lines.append('import logging')
         lines.append('import sys')
         lines.append('')
         lines.append('from MicroserviceBase.domain.service_base import ServiceBase')
         lines.append('from MicroserviceBase.factory import create_transport, create_registry')
         lines.append('')
         lines.append('')
         lines.append('logger = logging.getLogger("' + body.service_name + '")')
         lines.append('')
         lines.append('')
         lines.append('class ' + body.service_name + 'Service(ServiceBase):')
         lines.append('   """')
         lines.append((body.description or body.service_name + ' service.'))
         lines.append('   """')
         lines.append('')
         lines.append('   _SERVICE_INFO = {')
         lines.append("      'name': '" + body.service_name + "',")
         lines.append("      'description': '" + body.description.replace("'", "\\'") + "',")
         lines.append("      'shortdesc': '" + body.short_description.replace("'", "\\'") + "',")
         lines.append("      'group': '" + body.group.replace("'", "\\'") + "',")
         lines.append("      'tag': '" + body.tag.replace("'", "\\'") + "',")
         lines.append("      'version': '" + body.version + "',")
         lines.append("      'routing_key': '" + routing_key + "',")
         lines.append("      'gui_support': " + str(body.gui_support) + ",")
         lines.append("      'methods': [],")
         lines.append("      'methods_info': {},")
         lines.append('   }')

         for method in body.methods:
            method_name = method.name.strip()
            if not method_name:
               continue
            # Build parameter list for the def line
            param_names = ['self']
            for p in method.params:
               if p.name.strip():
                  param_names.append(p.name.strip())

            lines.append('')
            lines.append('   def svc_api_' + method_name + '(' + ', '.join(param_names) + '):')

            # Build docstring
            lines.append('      """')
            lines.append(method.description or method_name.replace('_', ' ').capitalize() + '.')
            if method.params:
               lines.append('')
               lines.append('**Arguments:**')
               for p in method.params:
                  if not p.name.strip():
                     continue
                  condition = 'required' if p.required else 'optional'
                  lines.append('')
                  lines.append('* ``' + p.name.strip() + '``')
                  lines.append('')
                  lines.append('  / *Condition*: ' + condition + ' / *Type*: ' + (p.type or 'str') + ' /')
                  lines.append('')
                  lines.append('  ' + p.name.strip().replace('_', ' ').capitalize() + '.')
            if method.return_type:
               lines.append('')
               lines.append('**Returns:**')
               lines.append('')
               lines.append('  / *Type*: ' + method.return_type + ' /')
               lines.append('')
               lines.append('  Result.')
            lines.append('      """')
            lines.append('      # TODO: Implement ' + method_name)
            lines.append('      pass')

         return '\n'.join(lines) + '\n'

      def _generate_main_py(body: ScaffoldRequest):
         """
Generate the main.py entry point.

**Arguments:**

* ``body``

  / *Condition*: required / *Type*: ScaffoldRequest /

  Scaffold request containing service metadata.
         """
         lines = []
         lines.append('import logging')
         lines.append('import os')
         lines.append('import sys')
         lines.append('')

         snake_name = _to_snake_case(body.service_name)
         lines.append('from ' + snake_name + ' import ' + body.service_name + 'Service')
         lines.append('from MicroserviceBase.factory import create_transport, create_registry')
         lines.append('')

         lines.append('logging.basicConfig(')
         lines.append("   format='%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s',")
         lines.append("   datefmt='%H:%M:%S',")
         lines.append('   level=logging.INFO,')
         lines.append(')')
         lines.append("logging.getLogger('pika').setLevel(logging.WARNING)")
         lines.append('')
         lines.append("logger = logging.getLogger('" + body.service_name + "')")
         lines.append('')
         lines.append('')
         lines.append('def main():')
         lines.append('   """')
         lines.append('Run the ' + body.service_name + ' service.')
         lines.append('   """')

         if body.transport == 'eventbus':
            lines.append("   config_path = os.path.join(os.path.dirname(__file__), 'config.jsonp')")
            lines.append("   transport = create_transport('eventbus', config_path=config_path,")
            lines.append("                                service_name='" + body.service_name + "')")
            lines.append("   registry = create_registry('eventbus', config_path=config_path,")
            lines.append("                              service_name='" + body.service_name + "')")
         else:
            lines.append("   transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],")
            lines.append("                                service_name='" + body.service_name + "')")
            lines.append("   registry = create_registry('rabbitmq', cmd_args=sys.argv[1:],")
            lines.append("                              service_name='" + body.service_name + "')")

         lines.append('')
         lines.append('   service = ' + body.service_name + 'Service(transport=transport, registry=registry)')
         lines.append('')
         lines.append('   try:')
         lines.append('      service.register_service()')
         lines.append("      logger.info('Service registered, starting serve()...')")
         lines.append('      service.serve()')
         lines.append('   except KeyboardInterrupt:')
         lines.append("      logger.info('KeyboardInterrupt caught')")
         lines.append('   except Exception as ex:')
         lines.append("      logger.error('Exception: %s: %s', type(ex).__name__, ex)")
         lines.append('   finally:')
         lines.append('      try:')
         lines.append('         service.unregister_service()')
         lines.append('      except Exception:')
         lines.append('         pass')
         lines.append('      try:')
         lines.append('         service.close()')
         lines.append('      except Exception:')
         lines.append('         pass')
         lines.append("      logger.info('Service stopped')")
         lines.append('')
         lines.append('')
         lines.append("if __name__ == '__main__':")
         lines.append('   main()')

         return '\n'.join(lines) + '\n'

      def _generate_dunder_main_py(body: ScaffoldRequest):
         """
Generate __main__.py entry point for ``python -m`` execution.

**Arguments:**

* ``body``

  / *Condition*: required / *Type*: ScaffoldRequest /

  Scaffold request containing service metadata.
         """
         lines = []
         lines.append('"""Entry point for running ' + body.service_name + ' as a package.')
         lines.append('')
         lines.append('Usage: python -m ' + body.service_name + ' [args]')
         lines.append('"""')
         lines.append('import os')
         lines.append('import sys')
         lines.append('')
         lines.append('# Ensure the service directory is on sys.path for local imports')
         lines.append('sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))')
         lines.append('')
         lines.append('from main import main')
         lines.append('')
         lines.append('main()')
         return '\n'.join(lines) + '\n'

      def _generate_config_jsonp(body: ScaffoldRequest):
         """
Generate config.jsonp for EventBus transport.

**Arguments:**

* ``body``

  / *Condition*: required / *Type*: ScaffoldRequest /

  Scaffold request containing service metadata.
         """
         routing_key = body.routing_key or ('service.' + _to_snake_case(body.service_name))
         config = {
            "transport": "eventbus",
            "routing_key": routing_key,
            "xpub_endpoint": "tcp://localhost:5555",
            "xsub_endpoint": "tcp://localhost:5556"
         }
         return json.dumps(config, indent=2) + '\n'

      def _generate_gui_html(body: ScaffoldRequest):
         """
Generate a basic GUI HTML template.

**Arguments:**

* ``body``

  / *Condition*: required / *Type*: ScaffoldRequest /

  Scaffold request containing service metadata.
         """
         return (
            '<div class="card">\n'
            '  <div class="card-header">\n'
            '    <h5>' + body.service_name + '</h5>\n'
            '    <small class="text-muted">'
            + (body.short_description or body.description or '') +
            '</small>\n'
            '  </div>\n'
            '  <div class="card-body">\n'
            '    <p>Custom GUI for ' + body.service_name + '.</p>\n'
            '    <!-- Add your service GUI here -->\n'
            '  </div>\n'
            '</div>\n'
         )

      def _generate_gui_js(body: ScaffoldRequest):
         """
Generate a basic GUI JS template.

**Arguments:**

* ``body``

  / *Condition*: required / *Type*: ScaffoldRequest /

  Scaffold request containing service metadata.
         """
         return (
            "/**\n"
            " * GUI for " + body.service_name + " service.\n"
            " */\n"
            "(function () {\n"
            "  'use strict';\n"
            "\n"
            "  var MM = window.MicroserviceManager;\n"
            "\n"
            "  function load" + body.service_name + "() {\n"
            "    console.log('" + body.service_name + " GUI loaded');\n"
            "  }\n"
            "\n"
            "  function unload" + body.service_name + "() {\n"
            "    console.log('" + body.service_name + " GUI unloaded');\n"
            "  }\n"
            "\n"
            "  // Expose load/unload to global scope for the service loader\n"
            "  window.load" + body.service_name + " = load" + body.service_name + ";\n"
            "  window.unload" + body.service_name + " = unload" + body.service_name + ";\n"
            "\n"
            "  // Initial load\n"
            "  load" + body.service_name + "();\n"
            "})();\n"
         )

      @app.post("/api/scaffold/generate")
      def scaffold_generate(body: ScaffoldRequest):
         """
Generate scaffolding for a new microservice project.
         """
         try:
            _validate_safe_name(body.service_name)
         except ValueError as exc:
            return {"status": "error", "error": str(exc)}

         snake_name = _to_snake_case(body.service_name)
         folder_name = body.service_name

         # Collect files: (relative_path, content)
         files = []
         files.append((snake_name + '.py', _generate_service_class(body)))
         files.append(('main.py', _generate_main_py(body)))
         files.append(('__main__.py', _generate_dunder_main_py(body)))

         if body.transport == 'eventbus':
            files.append(('config.jsonp', _generate_config_jsonp(body)))

         if body.gui_support:
            if body.gui_mode == 'schema' and body.gui_schema:
               files.append(('GUIs/gui_schema.json', json.dumps(body.gui_schema, indent=2)))
            else:
               files.append(('GUIs/service.html', body.custom_gui_html or _generate_gui_html(body)))
               files.append(('GUIs/service.js', body.custom_gui_js or _generate_gui_js(body)))

         if body.output_path:
            # Write to disk
            target_dir = os.path.join(body.output_path, folder_name)
            # Ensure generated files stay within the target directory
            real_target = os.path.realpath(target_dir)
            try:
               for rel_path, content in files:
                  full_path = os.path.join(target_dir, rel_path)
                  real_full = os.path.realpath(full_path)
                  if not real_full.startswith(real_target + os.sep) and real_full != real_target:
                     return {"status": "error", "error": f"Unsafe relative path: {rel_path!r}"}
                  os.makedirs(os.path.dirname(full_path), exist_ok=True)
                  with open(full_path, 'w', encoding='utf-8') as f:
                     f.write(content)
               logger.info("Scaffold files written to %s", target_dir)
               return {"status": "ok", "path": target_dir}
            except Exception as exc:
               logger.error("Scaffold write error: %s", exc, exc_info=True)
               return {"status": "error", "error": str(exc)}
         else:
            # Create in-memory ZIP
            import io
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
               for rel_path, content in files:
                  zf.writestr(folder_name + '/' + rel_path, content)
            zip_data = base64.b64encode(buf.getvalue()).decode('ascii')
            return {
               "status": "ok",
               "zip_data": zip_data,
               "filename": folder_name + ".zip"
            }

      # ---- New scaffold generator (v2 — multi-language, multi-GUI) ----

      class ScaffoldV2MethodParam(BaseModel):
         name: str = ""
         type: str = "string"
         required: bool = True
         description: str = ""

      class ScaffoldV2Method(BaseModel):
         name: str = ""
         params: List[ScaffoldV2MethodParam] = []
         return_type: str = "string"
         description: str = ""
         server_streaming: bool = False
         input_type: str = ""    # fully-qualified proto type (imported protos)
         output_type: str = ""   # fully-qualified proto type (imported protos)

      class ScaffoldV2Service(BaseModel):
         """One service block inside a multi-service scaffold (monorepo or
         multi_proto layout)."""
         name: str = ""
         methods: List[ScaffoldV2Method] = []
         # multi_proto-only: per-service .proto filename and verbatim text.
         # When set, the generator writes proto/<proto_file> with this
         # exact content (preserves comments / imports / packages).
         # Empty in monorepo mode.
         proto_file: str = ""
         proto_content: str = ""

      class ScaffoldV2Request(BaseModel):
         service_name: str
         version: str = "1.0.0"
         description: str = ""
         short_desc: str = ""
         group: str = ""
         tag: str = ""
         language: str = "python"       # "python" | "cpp"
         gui_type: str = "none"         # "none" | "html" | "qml" | "wasm" | "widget"
         client_grpc_kind: str = "google"  # "google" | "qt" | "google_vcpkg" — only used when gui_type != "none".
         server_grpc_kind: str = "msys2"   # "msys2" | "vcpkg" — toolchain the server is built with. Independent of client.
         gen_nomad: bool = True
         gen_build_scripts: bool = True
         gen_readme: bool = True
         gen_stubs: bool = True
         vcpkg_root: str = ""
         protoc_path: str = ""
         grpc_plugin_path: str = ""
         nomad_dc: str = "dc1"
         nomad_driver: str = "raw_exec"
         nomad_command: str = ""
         nomad_cpu: int = 100
         nomad_mem: int = 128
         nomad_consul_addr: str = "http://127.0.0.1:8500"
         methods: List[ScaffoldV2Method] = []
         output_path: str = ""
         proto_content_override: str = ""   # if non-empty, written verbatim to proto/<sn>.proto
         monorepo: bool = False             # when true, emit one project with N executables
         layout: str = ""                   # ""|"monorepo"|"multi_proto" - explicit layout
                                            # selector.  Takes precedence over `monorepo`
                                            # (kept for back-compat).  multi_proto = N
                                            # services in 1 binary; needs per-service
                                            # proto_file + proto_content.
         services: List[ScaffoldV2Service] = []  # for monorepo / multi_proto
         proto_package: str = ""            # real .proto `package X;` when importing

      class ParseProtoRequest(BaseModel):
         proto_content: str

      @app.post("/api/scaffold/parse-proto")
      def scaffold_parse_proto(body: ParseProtoRequest):
         """Parse a .proto file via protoc and return services/methods/params.

         Used by the Service Creator wizard's "Import .proto..." button.
         Returns a list of services (user picks one in the UI if > 1).
         """
         import os
         import tempfile
         try:
            from grpc_tools import protoc as grpc_protoc
            from google.protobuf import descriptor_pb2
         except ImportError:
            return {"status": "error",
                    "error": "grpc_tools / protobuf not installed on the bridge."}

         if not body.proto_content.strip():
            return {"status": "error", "error": "Empty .proto content."}

         # Scalar types the wizard + generated GUI know how to handle.
         _SCALAR = {
            1:  "double",   2:  "float",    3:  "int64",    4:  "uint64",
            5:  "int32",    6:  "fixed64",  7:  "fixed32",  8:  "bool",
            9:  "string",   12: "bytes",    13: "uint32",
            15: "sfixed32", 16: "sfixed64", 17: "sint32",   18: "sint64",
         }
         TYPE_MESSAGE = 11
         TYPE_ENUM = 14

         warnings = []
         with tempfile.TemporaryDirectory() as tmpdir:
            proto_path = os.path.join(tmpdir, "_import.proto")
            desc_path = os.path.join(tmpdir, "_import.pb")
            with open(proto_path, "w", encoding="utf-8") as f:
               f.write(body.proto_content)

            rc = grpc_protoc.main([
               "grpc_tools.protoc",
               f"--proto_path={tmpdir}",
               f"--descriptor_set_out={desc_path}",
               proto_path,
            ])
            if rc != 0:
               return {"status": "error",
                       "error": "protoc rejected the .proto (see bridge logs)."}

            with open(desc_path, "rb") as f:
               fds = descriptor_pb2.FileDescriptorSet()
               fds.ParseFromString(f.read())

         if not fds.file:
            return {"status": "error", "error": "Empty descriptor — no file parsed."}

         file_desc = fds.file[0]
         # Index all messages in the file by short name (no leading dot) so
         # we can resolve method input/output types.
         msgs = {m.name: m for m in file_desc.message_type}

         def _extract_fields(msg_name: str):
            """Return list of {name, type} dicts for all fields in msg_name."""
            msg = msgs.get(msg_name)
            if msg is None:
               warnings.append(f"Message '{msg_name}' not found in this file "
                               f"(imports are not resolved).")
               return []
            out = []
            for fld in msg.field:
               if fld.label == 3:   # LABEL_REPEATED
                  warnings.append(
                     f"Field '{msg_name}.{fld.name}' is repeated — "
                     f"generated GUI won't support lists.")
               if fld.type == TYPE_MESSAGE or fld.type == TYPE_ENUM:
                  warnings.append(
                     f"Field '{msg_name}.{fld.name}' is a "
                     f"{'nested message' if fld.type == TYPE_MESSAGE else 'enum'} — "
                     f"not supported in generated GUI.")
                  out.append({"name": fld.name, "type": "string"})
               else:
                  out.append({"name": fld.name, "type": _SCALAR.get(fld.type, "string")})
            return out

         def _first_field_type(msg_name: str) -> str:
            msg = msgs.get(msg_name)
            if not msg or not msg.field:
               return "string"
            f0 = msg.field[0]
            return _SCALAR.get(f0.type, "string")

         def _strip_pkg(qualified: str) -> str:
            # protoc emits ".pkg.sub.MsgName"; strip package prefix.
            return qualified.rsplit(".", 1)[-1]

         services = []
         for svc in file_desc.service:
            methods = []
            for m in svc.method:
               input_short  = _strip_pkg(m.input_type)
               output_short = _strip_pkg(m.output_type)
               # Fully-qualified types (descriptor names begin with a dot).
               input_fqn  = m.input_type.lstrip(".")
               output_fqn = m.output_type.lstrip(".")
               if m.client_streaming:
                  warnings.append(
                     f"Method '{svc.name}.{m.name}' uses client streaming — "
                     f"generated GUI only supports unary and server-streaming.")
               methods.append({
                  "name": m.name,
                  "input_type": input_fqn,            # e.g. "device.ChannelRequest"
                  "output_type": output_fqn,          # e.g. "device.ChannelCountResponse"
                  "params": _extract_fields(input_short),
                  "return_type": _first_field_type(output_short),
                  "server_streaming": bool(m.server_streaming),
                  "description": "",
               })
            services.append({
               "name": svc.name,
               "methods": methods,
            })

         if not services:
            return {"status": "error",
                    "error": "No 'service' block found in the .proto."}

         return {
            "status": "ok",
            "proto_package": file_desc.package,
            "services": services,
            "warnings": warnings,
         }

      @app.post("/api/scaffold/generate-v2")
      def scaffold_generate_v2(body: ScaffoldV2Request):
         """Generate scaffolding for a new microservice (v2 — Python/C++, multi-GUI)."""
         from ..scaffold import generate_scaffold, ScaffoldSpec
         from ..scaffold.generator import MethodSpec, MethodParam, ServiceBlock

         try:
            _validate_safe_name(body.service_name)
         except ValueError as exc:
            return {"status": "error", "error": str(exc)}

         # Resolve effective layout.  Explicit `layout` takes precedence;
         # `monorepo: true` is the legacy form.  Multi_proto requires per-
         # service proto_file + proto_content, so the JS wizard sets it
         # explicitly when the user picked >1 .proto files.
         effective_layout = body.layout
         if not effective_layout:
            effective_layout = "monorepo" if body.monorepo else ""

         # Convert services list (used by both monorepo and multi_proto) into
         # ServiceBlock dataclasses.  multi_proto entries also carry
         # proto_file + proto_content.
         mono_services = []
         if effective_layout in ("monorepo", "multi_proto") and body.services:
            for svc in body.services:
               try:
                  _validate_safe_name(svc.name)
               except ValueError as exc:
                  return {"status": "error",
                          "error": f"Invalid service name '{svc.name}': {exc}"}
               mono_services.append(ServiceBlock(
                  name=svc.name,
                  methods=[
                     MethodSpec(
                        name=m.name,
                        params=[MethodParam(name=p.name, type=p.type,
                                            required=p.required, description=p.description)
                                for p in m.params],
                        return_type=m.return_type,
                        description=m.description,
                        server_streaming=m.server_streaming,
                        input_type=m.input_type,
                        output_type=m.output_type,
                     )
                     for m in svc.methods
                  ],
                  proto_file=svc.proto_file,
                  proto_content=svc.proto_content,
               ))

         spec = ScaffoldSpec(
            service_name=body.service_name,
            version=body.version,
            description=body.description,
            short_desc=body.short_desc,
            group=body.group,
            tag=body.tag,
            language=body.language,
            gui_type=body.gui_type,
            client_grpc_kind=body.client_grpc_kind,
            server_grpc_kind=body.server_grpc_kind,
            gen_nomad=body.gen_nomad,
            gen_build_scripts=body.gen_build_scripts,
            gen_readme=body.gen_readme,
            gen_stubs=body.gen_stubs,
            vcpkg_root=body.vcpkg_root,
            protoc_path=body.protoc_path,
            grpc_plugin_path=body.grpc_plugin_path,
            nomad_dc=body.nomad_dc,
            nomad_driver=body.nomad_driver,
            nomad_command=body.nomad_command,
            nomad_cpu=body.nomad_cpu,
            nomad_mem=body.nomad_mem,
            nomad_consul_addr=body.nomad_consul_addr,
            methods=[
               MethodSpec(
                  name=m.name,
                  params=[MethodParam(name=p.name, type=p.type,
                                      required=p.required, description=p.description)
                          for p in m.params],
                  return_type=m.return_type,
                  description=m.description,
                  server_streaming=m.server_streaming,
                  input_type=m.input_type,
                  output_type=m.output_type,
               )
               for m in body.methods
            ],
            proto_content_override=body.proto_content_override,
            proto_package_override=body.proto_package,
            services=mono_services,
            layout=effective_layout or "monorepo",
         )

         try:
            file_map = generate_scaffold(spec)
         except Exception as exc:
            logger.error("Scaffold generation error: %s", exc, exc_info=True)
            return {"status": "error", "error": str(exc)}

         folder_name = body.service_name

         if body.output_path:
            target_dir = os.path.join(body.output_path, folder_name)
            real_target = os.path.realpath(target_dir)
            try:
               for rel_path, content in file_map.items():
                  full_path = os.path.join(target_dir, rel_path)
                  real_full = os.path.realpath(full_path)
                  if not real_full.startswith(real_target + os.sep) and real_full != real_target:
                     return {"status": "error", "error": f"Unsafe path: {rel_path!r}"}
                  os.makedirs(os.path.dirname(full_path), exist_ok=True)
                  with open(full_path, 'w', encoding='utf-8') as f:
                     f.write(content)
               logger.info("Scaffold v2 written to %s (%d files)",
                           target_dir, len(file_map))
               return {"status": "ok", "path": target_dir,
                       "file_count": len(file_map),
                       "files": sorted(file_map.keys())}
            except Exception as exc:
               logger.error("Scaffold v2 write error: %s", exc, exc_info=True)
               return {"status": "error", "error": str(exc)}
         else:
            import io
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
               for rel_path, content in file_map.items():
                  zf.writestr(folder_name + '/' + rel_path, content)
            zip_data = base64.b64encode(buf.getvalue()).decode('ascii')
            return {
               "status": "ok",
               "zip_data": zip_data,
               "filename": folder_name + ".zip",
               "file_count": len(file_map),
               "files": sorted(file_map.keys()),
            }

      # Mount static files for the GUI web application
      gui_path = os.path.join(
         os.path.dirname(__file__), '..', '..',
         'MicroserviceManagerGUI', 'web'
      )
      if os.path.isdir(gui_path):
         from fastapi.staticfiles import StaticFiles
         app.mount("/gui", StaticFiles(directory=gui_path, html=True), name="gui")
         logger.info("GUI mounted at /gui from %s", gui_path)
      else:
         logger.warning("GUI web folder not found at %s — /gui will not be available", gui_path)

      self._app = app

   def start(self, request_handler, services_info_provider):
      """
Start the FastAPI server in a background thread.

**Arguments:**

* ``request_handler``

  / *Condition*: required / *Type*: callable /

  Callable(request_data, exchange, routing_key) -> response dict.

* ``services_info_provider``

  / *Condition*: required / *Type*: callable /

  Callable() -> services info dict.
      """
      try:
         import fastapi  # noqa: F401
         import uvicorn  # noqa: F401
      except ImportError:
         raise ImportError(
            "The 'fastapi' and 'uvicorn' libraries are required for FastAPIBridge. "
            "Install them with: pip install fastapi uvicorn"
         )

      self._request_handler = request_handler
      self._services_info_provider = services_info_provider
      self._build_app()

      self._thread = threading.Thread(target=self._run_server, daemon=True)
      self._thread.start()
      logger.info("FastAPI bridge started on http://%s:%s", self._host, self._port)

   def _run_server(self):
      """
Run uvicorn in its own thread with a dedicated event loop.
      """
      import uvicorn
      import logging

      loop = asyncio.new_event_loop()
      asyncio.set_event_loop(loop)
      self._server_loop = loop

      # Silence the uvicorn access log for the high-frequency background
      # polls from the GUI (BridgeControl every 3s, InfraStatus every 5s).
      # They're all 200 OK and would otherwise flood launcher.log.
      class _NoisyPollFilter(logging.Filter):
         _QUIET = (
            'GET /api/version',
            'GET /api/consul/health',
            'GET /api/nomad/health',
         )
         def filter(self, record):
            msg = record.getMessage()
            return not any(p in msg for p in self._QUIET)

      logging.getLogger('uvicorn.access').addFilter(_NoisyPollFilter())

      config = uvicorn.Config(
         self._app,
         host=self._host,
         port=self._port,
         log_level="info",
      )
      self._server = uvicorn.Server(config)
      # Use loop.run_until_complete instead of server.run() so the server
      # runs on OUR event loop. server.run() calls asyncio.run() which
      # creates a different loop, breaking broadcast_update's
      # run_coroutine_threadsafe calls.
      loop.run_until_complete(self._server.serve())

   def wait(self):
      """
Block the calling thread until the server thread exits.

Uses a loop with timeout so that KeyboardInterrupt can be caught on Windows.
      """
      if self._thread is not None:
         while self._thread.is_alive():
            self._thread.join(timeout=1)

   def stop(self):
      """
Stop the FastAPI server.
      """
      if self._server is not None:
         self._server.should_exit = True
      if self._thread is not None:
         try:
            self._thread.join(timeout=5)
         except (KeyboardInterrupt, SystemExit):
            pass
      logger.info("FastAPI bridge stopped")

   def broadcast_update(self, services_info):
      """
Push a services update to all connected WebSocket clients.

**Arguments:**

* ``services_info``

  / *Condition*: required / *Type*: dict /

  dict of all current service information.
      """
      if not self._ws_clients or self._server_loop is None:
         return

      message = json.dumps({
         "action": "services_update",
         "data": services_info,
      })

      async def _send_to_all():
         disconnected = set()
         with self._ws_clients_lock:
            clients = list(self._ws_clients)
         for client in clients:
            try:
               await client.send_text(message)
            except (ConnectionError, RuntimeError):
               logger.debug("Failed to send to WebSocket client, marking as disconnected", exc_info=True)
               disconnected.add(client)
         if disconnected:
            with self._ws_clients_lock:
               self._ws_clients -= disconnected

      future = asyncio.run_coroutine_threadsafe(_send_to_all(), self._server_loop)
      try:
         future.result(timeout=5)
      except (TimeoutError, RuntimeError):
         logger.debug("Timed out broadcasting update to WebSocket clients", exc_info=True)
