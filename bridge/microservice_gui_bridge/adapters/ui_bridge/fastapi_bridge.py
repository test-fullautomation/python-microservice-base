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

      def _get_nomad_agent():
         """Get the managed Nomad agent subprocess info."""
         if not hasattr(bridge, '_nomad_agent_proc'):
            bridge._nomad_agent_proc = None
            bridge._nomad_agent_log = []
         return bridge._nomad_agent_proc

      @app.post("/api/nomad/agent/start")
      def nomad_agent_start(body: NomadAgentStartBody):
         import subprocess, shutil, threading

         # Check if already running
         proc = _get_nomad_agent()
         if proc and proc.poll() is None:
            return {"success": False,
                    "message": "Nomad agent already running (PID %d)" % proc.pid,
                    "pid": proc.pid}

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
         if not proc or proc.poll() is not None:
            bridge._nomad_agent_proc = None
            return {"success": True, "message": "Nomad agent not running"}

         pid = proc.pid
         logger.info('Stopping Nomad agent (PID %d)', pid)
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
         return {"success": True,
                 "message": "Nomad agent stopped (PID %d)" % pid}

      @app.get("/api/nomad/agent/status")
      def nomad_agent_status():
         proc = _get_nomad_agent()
         running = proc is not None and proc.poll() is None
         return {
            "running": running,
            "pid": proc.pid if running else None,
            "nomad_url": getattr(bridge, '_nomad_url', None),
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
         nc = _get_nomad_client()
         if not nc:
            # Auto-configure from env or default
            url = os.environ.get('NOMAD_ADDR', 'http://127.0.0.1:4646')
            nc = _ensure_nomad(url)
         if not nc:
            return {"status": "not configured"}
         try:
            info = nc.agent_self()
            member = info.get('member', {})
            return {"status": "ok", "server": member.get('Name', ''),
                    "address": bridge._nomad_url}
         except Exception as e:
            return {"status": "error", "message": str(e)}

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

      loop = asyncio.new_event_loop()
      asyncio.set_event_loop(loop)
      self._server_loop = loop

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
