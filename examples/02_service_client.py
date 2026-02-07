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
# File: 02_service_client.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / February 2026.
#
# Description:
#   Example of calling a running service via RPC.
#   Demonstrates how to use the transport adapter to send requests
#   and receive responses from a target service.
#
# Prerequisites:
#   1. RabbitMQ server running (default: localhost:5672)
#   2. The Calculator service from 01_basic_service.py must be running
#
# Usage:
#   python 02_service_client.py --host localhost --port 5672
#
# *******************************************************************************
"""
Service Client Example.

This example demonstrates how to:
1. Create a transport adapter for client-side RPC calls
2. Build a ServiceRequest with method name and arguments
3. Send an RPC call and receive a ServiceResponse
4. Parse the response to extract result data

Prerequisites:
    - RabbitMQ server running
    - Calculator service (01_basic_service.py) running
"""

import sys
from pathlib import Path

# Add MicroserviceBase to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from MicroserviceBase.domain.service_base import ServiceBase
from MicroserviceBase.factory import create_transport


def main():
   """
Run the service client example.
   """
   # Create a transport adapter (same factory, no registry needed for client)
   transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],
                                service_name='Client')

   # Define the target service's routing key and exchange
   exchange = 'services_request'
   routing_key = 'service.calculator'

   try:
      # Call svc_api_add(3, 5)
      request_data = ServiceBase.create_request_data('svc_api_add', [3, 5])
      print(f" [>] Calling svc_api_add(3, 5) ...")
      response = transport.rpc_call(request_data, exchange, routing_key)
      print(f" [<] Response: {response}")

      # Call svc_api_subtract(10, 4)
      request_data = ServiceBase.create_request_data('svc_api_subtract', [10, 4])
      print(f" [>] Calling svc_api_subtract(10, 4) ...")
      response = transport.rpc_call(request_data, exchange, routing_key)
      print(f" [<] Response: {response}")

      # Call svc_api_multiply(7, 6)
      request_data = ServiceBase.create_request_data('svc_api_multiply', [7, 6])
      print(f" [>] Calling svc_api_multiply(7, 6) ...")
      response = transport.rpc_call(request_data, exchange, routing_key)
      print(f" [<] Response: {response}")

      # Call svc_api_get_version()
      request_data = ServiceBase.create_request_data('svc_api_get_version', None)
      print(f" [>] Calling svc_api_get_version() ...")
      response = transport.rpc_call(request_data, exchange, routing_key)
      print(f" [<] Response: {response}")

   except KeyboardInterrupt:
      print(f" [*] Interrupted by user.")
   finally:
      transport.disconnect()
      print(f" [*] Client disconnected.")


if __name__ == '__main__':
   main()
