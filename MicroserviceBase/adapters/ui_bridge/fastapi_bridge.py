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
import json
import logging
import os
import threading
import zipfile

from ...ports.ui_bridge import UIBridgePort

logger = logging.getLogger(__name__)


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

  / *Condition*: optional / *Type*: str /

  Host to bind the server to.

* ``port``

  / *Condition*: optional / *Type*: int /

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

         try:
            services_info = bridge._services_info_provider() if bridge._services_info_provider else {}
            version = ""
            if service_name in services_info:
               version = services_info[service_name].get("version", "")

            target_dir = os.path.join(gui_web_path, service_name + version)
            os.makedirs(target_dir, exist_ok=True)

            zip_bytes = base64.b64decode(result["result_data"])
            zip_path = os.path.join(target_dir, "received_files.zip")
            with open(zip_path, "wb") as f:
               f.write(zip_bytes)

            with zipfile.ZipFile(zip_path, "r") as zf:
               zf.extractall(target_dir)

            os.remove(zip_path)
            logger.info("GUI resources extracted to %s", target_dir)
            return {"status": "ok", "path": target_dir}
         except Exception as exc:
            logger.error("Failed to extract GUI resources: %s", exc, exc_info=True)
            return {"error": str(exc)}

      # Mount static files for the GUI web application
      gui_path = os.path.join(
         os.path.dirname(__file__), '..', '..',
         'MicroserviceManagerGUI', 'web'
      )
      if os.path.isdir(gui_path):
         from fastapi.staticfiles import StaticFiles
         app.mount("/gui", StaticFiles(directory=gui_path, html=True), name="gui")

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
