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
# File: 05_alias_routing.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / February 2026.
#
# Description:
#   Example demonstrating alias routing through the Service Registry.
#   Shows how to configure user-friendly method aliases that map to
#   specific service methods with pre-configured arguments.
#
# Prerequisites:
#   1. RabbitMQ server running (default: localhost:5672)
#   2. The Calculator service from 01_basic_service.py must be running
#   3. The Service Registry from 03_service_registry.py must be running
#
# Usage:
#   python 05_alias_routing.py --host localhost --port 5672
#
# *******************************************************************************
"""
Alias Routing Example.

This example demonstrates how to:
1. Configure method aliases in the Service Registry
2. Call services using user-friendly alias names
3. Use argument templates with ${input} substitution
4. Route requests transparently through the Registry

Alias routing allows:
- User-friendly names for complex service methods
- Pre-configured arguments (only ${input} needs to be provided)
- Transparent forwarding (caller doesn't need to know the target service)
- Centralized routing configuration

Example alias configuration:
    {
        "double": {
            "Service name": "Calculator",
            "Method name": "svc_api_multiply",
            "Arguments": "${input},2"
        },
        "add_ten": {
            "Service name": "Calculator",
            "Method name": "svc_api_add",
            "Arguments": "${input},10"
        }
    }

Prerequisites:
    - Calculator service (01_basic_service.py) running
    - Service Registry (03_service_registry.py) running
"""

import sys
import json
from pathlib import Path

# Add MicroserviceBase to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from MicroserviceBase.domain.service_base import ServiceBase
from MicroserviceBase.factory import create_transport


def main():
   """
Run the alias routing example.
   """
   transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],
                                service_name='AliasClient')

   exchange = 'services_request'
   registry_routing_key = 'service.registry'

   try:
      # Step 1: Configure aliases in the Registry
      alias_config = {
         "double": {
            "Service name": "Calculator",
            "Method name": "svc_api_multiply",
            "Arguments": "${input},2",
         },
         "add_ten": {
            "Service name": "Calculator",
            "Method name": "svc_api_add",
            "Arguments": "${input},10",
         },
      }

      print(" [*] Configuring aliases in the Service Registry...")
      request_data = ServiceBase.create_request_data(
         'svc_api_update_alias_conf',
         [json.dumps(alias_config)],
      )
      response = transport.rpc_call(request_data, exchange, registry_routing_key)
      print(f" [<] Alias config response: {response}")

      # Step 2: Call via alias "double" with input 7
      # This will be routed to Calculator.svc_api_multiply(7, 2) -> 14
      print(f"\n [>] Calling alias 'double' with input 7 ...")
      request_data = ServiceBase.create_request_data('double', ['7'])
      response = transport.rpc_call(request_data, exchange, registry_routing_key)
      print(f" [<] Result: {response}")

      # Step 3: Call via alias "add_ten" with input 25
      # This will be routed to Calculator.svc_api_add(25, 10) -> 35
      print(f"\n [>] Calling alias 'add_ten' with input 25 ...")
      request_data = ServiceBase.create_request_data('add_ten', ['25'])
      response = transport.rpc_call(request_data, exchange, registry_routing_key)
      print(f" [<] Result: {response}")

      # Step 4: Verify alias configuration
      print(f"\n [>] Retrieving current alias configuration ...")
      request_data = ServiceBase.create_request_data('svc_api_get_alias_conf', None)
      response = transport.rpc_call(request_data, exchange, registry_routing_key)
      print(f" [<] Alias config: {response}")

   except KeyboardInterrupt:
      print(f" [*] Interrupted by user.")
   finally:
      transport.disconnect()
      print(f" [*] Client disconnected.")


if __name__ == '__main__':
   main()
