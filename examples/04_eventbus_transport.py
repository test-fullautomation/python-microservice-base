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
# File: 04_eventbus_transport.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / February 2026.
#
# Description:
#   Example demonstrating MicroserviceBase with EventBus transport.
#   Shows how to use a JSONP config file instead of CLI arguments,
#   and how to swap transports without changing service code.
#
# Prerequisites:
#   1. RabbitMQ server running (default: localhost:5672)
#   2. EventBusClient package installed
#   3. A JSONP config file (see example below)
#
# Usage:
#   python 04_eventbus_transport.py
#
# *******************************************************************************
"""
EventBus Transport Example.

This example demonstrates how to:
1. Use EventBus transport instead of direct RabbitMQ (pika)
2. Configure transport via a JSONP config file
3. Swap transports without changing the service code
4. Use the factory to create EventBus-based adapters

Prerequisites:
    - RabbitMQ server running
    - EventBusClient package installed

The EventBus transport provides:
- JSONP-based configuration (no CLI argument parsing)
- Async message handling via aio_pika under the hood
- Topic and Fanout exchange handlers
- Shared configuration for derivative clients (registry, updates)

Example JSONP config file (config.jsonp):
    {
        "host": "localhost",
        "port": 5672,
        "username": "guest",
        "password": "guest",
        "exchange_name": "services_request",
        "exchange_handler": "TopicExchangeHandler"
    }
"""

import sys
import json
import tempfile
from pathlib import Path

# Add MicroserviceBase to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from MicroserviceBase.domain.service_base import ServiceBase
from MicroserviceBase.factory import create_transport, create_registry


class GreeterService(ServiceBase):
   """
A greeting service using EventBus transport.

Same service code as any other service -- only the transport wiring differs.
   """

   _SERVICE_INFO = {
      'name': 'Greeter',
      'description': 'A greeting service demonstrating EventBus transport.',
      'shortdesc': 'Greeting service.',
      'group': 'examples',
      'tag': 'v1',
      'version': '1.0.0',
      'routing_key': 'service.greeter',
      'gui_support': False,
      'methods': [],
      'methods_info': {},
   }

   def svc_api_hello(self, name):
      """
Greet someone by name.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Name of the person to greet.

**Returns:**

  / *Type*: str /

  Greeting message.
      """
      return f"Hello, {name}! Welcome to the EventBus-powered service."

   def svc_api_goodbye(self, name):
      """
Say goodbye to someone.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Name of the person.

**Returns:**

  / *Type*: str /

  Farewell message.
      """
      return f"Goodbye, {name}! See you next time."


def create_config_file():
   """
Create a temporary JSONP config file for the EventBus transport.

In production, this file would be a persistent configuration file.
   """
   config = {
      "host": "localhost",
      "port": 5672,
      "username": "guest",
      "password": "guest",
      "exchange_name": "services_request",
      "exchange_handler": "TopicExchangeHandler",
   }
   config_file = tempfile.NamedTemporaryFile(
      mode='w', suffix='.jsonp', delete=False,
   )
   json.dump(config, config_file)
   config_file.close()
   return config_file.name


def main():
   """
Run the Greeter service with EventBus transport.
   """
   config_path = create_config_file()
   print(f" [*] Using config: {config_path}")

   # Create transport and registry using EventBus instead of RabbitMQ
   # Note: only the factory call changes -- the service code is identical
   transport = create_transport('eventbus', config_path=config_path)
   registry = create_registry('eventbus', config_path=config_path,
                              update_exchange_name='services_update')

   service = GreeterService(transport=transport, registry=registry)

   try:
      service.register_service()
      service.serve()
   except KeyboardInterrupt:
      print(f" [*] Interrupted by user.")
   finally:
      service.unregister_service()
      service.close()
      # Clean up temp config
      Path(config_path).unlink(missing_ok=True)
      print(f" [*] Service stopped.")


if __name__ == '__main__':
   main()
