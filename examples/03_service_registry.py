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
# File: 03_service_registry.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / February 2026.
#
# Description:
#   Example of running the Service Registry.
#   The registry is the central discovery hub that tracks all services,
#   handles registration events, and broadcasts updates to UI clients.
#
# Prerequisites:
#   1. RabbitMQ server running (default: localhost:5672)
#
# Usage:
#   python 03_service_registry.py --host localhost --port 5672
#
# *******************************************************************************
"""
Service Registry Example.

This example demonstrates how to:
1. Create and run the ServiceRegistry (central discovery hub)
2. Configure the realtime update exchange for UI clients
3. Handle service registration and unregistration events
4. Broadcast service list updates to all connected UI clients

The Service Registry:
- Listens on the 'service_information' topic exchange for register/unregister events
- Maintains a dict of all currently registered services
- Broadcasts the full service list when changes occur (via fanout exchange)
- Exposes its own API methods for querying service information
- Supports alias routing via alias.json configuration
"""

import sys
import threading
from pathlib import Path

# Add MicroserviceBase to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from MicroserviceBase.domain.service_registry import ServiceRegistry
from MicroserviceBase.factory import create_transport, create_registry


def main():
   """
Run the Service Registry.
   """
   # Create transport and registry adapters
   # The update_exchange_name is used for realtime broadcasts to UI clients
   transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],
                                service_name='ServiceRegistry')
   registry = create_registry('rabbitmq', cmd_args=sys.argv[1:],
                              service_name='ServiceRegistry',
                              update_exchange_name='services_update')

   # Create the ServiceRegistry with injected dependencies
   service_registry = ServiceRegistry(transport=transport, registry=registry)

   info = service_registry.get_service_info()
   print(f" [*] Service Registry: {info.name} v{info.version}")
   print(f" [*] Routing key: {info.routing_key}")
   print(f" [*] Update exchange: {registry.get_update_channel_name()}")

   try:
      # Start the discovery thread that listens for service events
      # This thread subscribes to the 'service_information' exchange
      # and calls handle_update() when services register or unregister
      discovery_thread = threading.Thread(
         target=registry.subscribe_to_events,
         args=(lambda ch, method, props, body: _on_service_event(
            service_registry, registry, body
         ),),
         daemon=True,
      )
      discovery_thread.start()

      # Register the registry itself as a service
      service_registry.register_service()

      # Start serving RPC requests (blocks until interrupted)
      print(f" [*] Registry is running. Press CTRL+C to stop.")
      service_registry.serve()
   except KeyboardInterrupt:
      print(f" [*] Interrupted by user.")
   finally:
      service_registry.unregister_service()
      service_registry.close()
      registry.cleanup()
      print(f" [*] Registry stopped.")


def _on_service_event(service_registry, registry_adapter, body):
   """
Handle a service registration or unregistration event.

Called by the discovery thread when a service publishes to the
service_information exchange.
   """
   import json

   if isinstance(body, bytes):
      body = json.loads(body.decode('utf-8'))

   print(f" [>] Service event received: {body}")
   service_registry.handle_update(body)
   service_registry.notify_updates()


if __name__ == '__main__':
   main()
