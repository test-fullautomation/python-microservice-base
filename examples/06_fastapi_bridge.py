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
# File: 06_fastapi_bridge.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / February 2026.
#
# Description:
#   Example demonstrating the FastAPI UI bridge.
#   Shows how to expose microservices via a REST API and WebSocket,
#   enabling browser-based and third-party client access.
#
# Prerequisites:
#   1. RabbitMQ server running (default: localhost:5672)
#   2. FastAPI installed: pip install fastapi uvicorn
#   3. The Service Registry from 03_service_registry.py must be running
#   4. At least one service (e.g., 01_basic_service.py) must be running
#
# Usage:
#   python 06_fastapi_bridge.py --host localhost --port 5672
#
# Endpoints:
#   - POST http://localhost:1112/api/request  (invoke a service method)
#   - GET  http://localhost:1112/api/services (list registered services)
#   - WS   ws://localhost:1112/ws/updates    (realtime service updates)
#   - GET  http://localhost:1112/docs         (Swagger documentation)
#
# *******************************************************************************
"""
FastAPI UI Bridge Example.

This example demonstrates how to:
1. Create a FastAPI bridge for browser-based access to microservices
2. Expose a REST endpoint for invoking service methods
3. Expose a REST endpoint for listing registered services
4. Push realtime service updates via WebSocket
5. Access auto-generated Swagger documentation

The FastAPI bridge provides:
- REST API for any HTTP client (curl, browser, Python requests)
- WebSocket for realtime push notifications
- Swagger UI at /docs for interactive API exploration
- Decoupled UI layer (any frontend can connect)

Example HTTP requests:
    # List all services
    curl http://localhost:1112/api/services

    # Call a service method
    curl -X POST http://localhost:1112/api/request \\
         -H "Content-Type: application/json" \\
         -d '{"method": "svc_api_add", "args": [3, 5],
              "exchange": "services_request",
              "routing_key": "service.calculator"}'
"""

import sys
import threading
from pathlib import Path

# Add MicroserviceBase to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from MicroserviceBase.factory import create_transport, create_registry, create_ui_bridge


def main():
   """
Run the FastAPI bridge example.
   """
   # Create transport to forward requests to services
   transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],
                                service_name='FastAPIBridge')
   registry = create_registry('rabbitmq', cmd_args=sys.argv[1:],
                              service_name='FastAPIBridge',
                              update_exchange_name='services_update')

   # Track registered services (populated from registry events)
   services_info = {}

   def request_handler(request_data, exchange='services_request', routing_key=''):
      """
Forward a service request from the UI to the target service via transport.
      """
      return transport.rpc_call(request_data, exchange, routing_key)

   def services_info_provider():
      """
Return the current registry state for the GET /api/services endpoint.
      """
      return services_info

   # Create and start the FastAPI bridge
   bridge = create_ui_bridge('fastapi', host='localhost', port=1112)

   print(" [*] FastAPI Bridge Configuration:")
   print(" [*]   REST API:  http://localhost:1112/api/request")
   print(" [*]   Services:  http://localhost:1112/api/services")
   print(" [*]   WebSocket: ws://localhost:1112/ws/updates")
   print(" [*]   Swagger:   http://localhost:1112/docs")

   try:
      # Start listening for registry updates via the fanout exchange.
      # This receives the full services dict on every change (same as the Electron GUI).
      def _listen_for_updates():
         registry.subscribe_to_updates(
            lambda data: _on_update(bridge, services_info, data)
         )

      update_thread = threading.Thread(target=_listen_for_updates, daemon=True)
      update_thread.start()

      # Start the FastAPI bridge
      print(" [*] Starting FastAPI bridge. Press CTRL+C to stop.")
      bridge.start(request_handler, services_info_provider)

      # Block the main thread until the server is stopped
      bridge.wait()
   except KeyboardInterrupt:
      pass
   finally:
      print("\n [*] Shutting down...")
      try:
         bridge.stop()
         transport.disconnect()
         registry.cleanup()
      except (KeyboardInterrupt, SystemExit, Exception):
         pass
      print(" [*] Bridge stopped.")


def _on_update(bridge, services_info, data):
   """
Handle a services update from the Registry's fanout exchange.

The data is the full services dict (all currently online services).
   """
   services_info.clear()
   services_info.update(data)
   bridge.broadcast_update(services_info)
   print(f" [>] Services updated: {list(services_info.keys())}")


if __name__ == '__main__':
   main()
