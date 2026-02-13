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

            logger.info("GUI resources extracted to %s", target_dir)
            return {"status": "ok", "path": target_dir}
         except Exception as exc:
            logger.error("Failed to extract GUI resources: %s", exc, exc_info=True)
            return {"error": str(exc)}
         finally:
            if os.path.exists(zip_path):
               os.remove(zip_path)

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
            from ..local_hub.local_hub_manager import LocalHubManager
            # Prefer env var (set by launcher.py for packaged apps),
            # fall back to relative path for development mode.
            hub_config_path = os.environ.get('DASGUI_HUB_CONFIG')
            if not hub_config_path:
               hub_config_path = os.path.join(
                  os.path.dirname(__file__), '..', '..',
                  'MicroserviceManagerGUI', 'python', 'hub_processes.json'
               )
            bridge._local_hub_manager = LocalHubManager(
               config_path=hub_config_path
            )
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
         return mgr.stop_hub()

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
