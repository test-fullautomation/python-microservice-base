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
# File: 01_basic_service.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / February 2026.
#
# Description:
#   Basic example of creating a microservice with MicroserviceBase.
#   Demonstrates how to define API methods, register with the broker,
#   and start serving RPC requests.
#
# Prerequisites:
#   1. RabbitMQ server running (default: localhost:5672)
#
# Usage:
#   python 01_basic_service.py --host localhost --port 5672
#
# *******************************************************************************
"""
Basic Microservice Example.

This example demonstrates how to:
1. Define a service by extending ServiceBase
2. Expose API methods with the svc_api_ prefix
3. Write docstrings that generate API documentation automatically
4. Create a transport and registry via the factory
5. Register the service and start serving requests

The service will:
- Connect to RabbitMQ
- Register itself with the Service Registry
- Start consuming RPC requests on its routing key
- Respond to method calls with structured ServiceResponse messages
"""

import sys
from pathlib import Path

# Add MicroserviceBase to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from MicroserviceBase.domain.service_base import ServiceBase
from MicroserviceBase.factory import create_transport, create_registry


class CalculatorService(ServiceBase):
   """
A simple calculator service.

Demonstrates the svc_api_ convention and docstring-based API discovery.
   """

   _SERVICE_INFO = {
      'name': 'Calculator',
      'description': 'A simple calculator service for basic arithmetic.',
      'shortdesc': 'Basic arithmetic operations.',
      'group': 'examples',
      'tag': 'v1',
      'version': '1.0.0',
      'routing_key': 'service.calculator',
      'gui_support': False,
      'methods': [],
      'methods_info': {},
   }

   def svc_api_add(self, a, b):
      """
Add two numbers.

**Arguments:**

* ``a``

  / *Condition*: required / *Type*: int /

  First number.

* ``b``

  / *Condition*: required / *Type*: int /

  Second number.

**Returns:**

  / *Type*: int /

  Sum of a and b.
      """
      return int(a) + int(b)

   def svc_api_subtract(self, a, b):
      """
Subtract b from a.

**Arguments:**

* ``a``

  / *Condition*: required / *Type*: int /

  First number.

* ``b``

  / *Condition*: required / *Type*: int /

  Number to subtract.

**Returns:**

  / *Type*: int /

  Difference of a and b.
      """
      return int(a) - int(b)

   def svc_api_multiply(self, a, b):
      """
Multiply two numbers.

**Arguments:**

* ``a``

  / *Condition*: required / *Type*: int /

  First number.

* ``b``

  / *Condition*: required / *Type*: int /

  Second number.

**Returns:**

  / *Type*: int /

  Product of a and b.
      """
      return int(a) * int(b)


def main():
   """
Run the Calculator service.
   """
   # Create transport and registry adapters via factory
   transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],
                                service_name='Calculator')
   registry = create_registry('rabbitmq', cmd_args=sys.argv[1:],
                              service_name='Calculator')

   # Create the service with injected dependencies
   service = CalculatorService(transport=transport, registry=registry)

   try:
      # Register with the Service Registry
      service.register_service()

      # Start serving (blocks until interrupted)
      service.serve()
   except KeyboardInterrupt:
      print(f" [*] Interrupted by user.")
   finally:
      service.unregister_service()
      service.close()
      print(f" [*] Service stopped.")


if __name__ == '__main__':
   main()
