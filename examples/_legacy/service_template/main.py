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
# File: main.py
#
# Description:
#   Service template — copy this folder and rename to create a new service.
#   The Local Hub requires main.py (or __main__.py) as the entry point.
#
# Usage:
#   python -m service_template --host localhost --port 5672
#   python main.py --host localhost --port 5672
#
# *******************************************************************************
"""
Service Template.

Copy this folder and customize it to create your own microservice.

Steps:
1. Rename the folder to match your service name.
2. Update _SERVICE_INFO with your service metadata.
3. Add your own svc_api_ methods.
4. (Optional) Set 'gui_support': True and add GUI files under GUIs/.
5. (Optional) Set 'downloadable': True to let users download this service
   as a ZIP from the Service Manager GUI.
"""

import logging
import os
import sys
from pathlib import Path

# Add MicroserviceBase to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from MicroserviceBase.domain.service_base import ServiceBase
from MicroserviceBase.factory import create_transport, create_registry

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
_log_file = Path(__file__).parent / "my_service_debug.log"
_fmt = logging.Formatter(
   "%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
   datefmt="%H:%M:%S",
)
_fh = logging.FileHandler(str(_log_file), mode='w')
_fh.setFormatter(_fmt)
logging.root.addHandler(_fh)
# Only add StreamHandler when running interactively (not piped by ProcessHub)
if sys.stderr.isatty():
   _sh = logging.StreamHandler()
   _sh.setFormatter(_fmt)
   logging.root.addHandler(_sh)
logging.root.setLevel(logging.INFO)
logging.getLogger("pika").setLevel(logging.WARNING)

logger = logging.getLogger("MyService")

# ---------------------------------------------------------------------------
# Service definition
# ---------------------------------------------------------------------------


class MyService(ServiceBase):
   """
   A template service — replace with your own description.
   """

   _SERVICE_INFO = {
      # ---- Required ----
      'name': 'MyService',               # Unique service name
      'version': '1.0.0',                # Semantic version
      'routing_key': 'service.myservice', # RabbitMQ routing key

      # ---- Display (shown in Service Manager GUI) ----
      'description': 'A template microservice — replace with your own.',
      'shortdesc': 'Template service.',
      'group': 'examples',               # Sidebar group in the GUI
      'tag': 'v1',

      # ---- Features ----
      'gui_support': False,   # True → serve GUI files from GUIs/ folder
      'downloadable': False,  # True → allow ZIP download from the GUI

      # ---- Auto-populated at runtime (leave empty) ----
      'methods': [],
      'methods_info': {},
   }

   # ------------------------------------------------------------------
   # API methods — must start with svc_api_
   # ------------------------------------------------------------------

   def svc_api_hello(self, name):
      """
Say hello.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  The name to greet.

**Returns:**

  / *Type*: str /

  A greeting message.
      """
      return f"Hello, {name}! Welcome to MyService."

   def svc_api_echo(self, message):
      """
Echo a message back.

**Arguments:**

* ``message``

  / *Condition*: required / *Type*: str /

  The message to echo.

**Returns:**

  / *Type*: str /

  The same message.
      """
      return message


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
   """
   Run the service.
   """
   service_name = MyService._SERVICE_INFO['name']

   transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],
                                service_name=service_name)
   registry = create_registry('rabbitmq', cmd_args=sys.argv[1:],
                               service_name=service_name)

   service = MyService(transport=transport, registry=registry)

   try:
      logger.info("Registering service '%s' ...", service_name)
      service.register_service()
      logger.info("Service registered. Starting serve() ...")
      service.serve()
   except KeyboardInterrupt:
      logger.info("KeyboardInterrupt — stopping service.")
   except Exception as ex:
      logger.error("Unexpected error: %s: %s", type(ex).__name__, ex)
   finally:
      try:
         service.unregister_service()
      except Exception as ex:
         logger.error("unregister_service() failed: %s", ex)
      try:
         service.close()
      except Exception as ex:
         logger.error("close() failed: %s", ex)
      logger.info("Service stopped.")
      sys.stdout.flush()
      sys.stderr.flush()


if __name__ == '__main__':
   main()
