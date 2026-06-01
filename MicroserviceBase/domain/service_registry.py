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
# File: service_registry.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Pure domain ServiceRegistry -- service tracking, alias routing, event handling.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import json
import logging
import threading
import time
import uuid

from .service_base import ServiceBase
from .messages import ResultType, ServiceResponse
from .exceptions import ServiceNotFoundError

logger = logging.getLogger(__name__)


class ServiceRegistry(ServiceBase):
   """
Pure domain registry that tracks services, handles aliases, and routes requests.
   """

   _SERVICE_INFO = {
      'name': 'ServiceRegistry',
      'description': 'One-stop service providing complete details on all system services as requested by users.',
      'shortdesc': 'Registry service',
      'group': '',
      'tag': '',
      'version': '1.0.0',
      'routing_key': 'abcxyz',
      'gui_support': False,
      'methods': [],
   }

   ALIAS_CONF_PATH = "alias.json"

   def __init__(self, transport=None, registry=None):
      """
Initialize the domain ServiceRegistry.

**Arguments:**

* ``transport``

  / *Condition*: optional / *Type*: TransportPort /

  A TransportPort implementation.

* ``registry``

  / *Condition*: optional / *Type*: ServiceRegistryPort /

  A ServiceRegistryPort implementation.
      """
      super().__init__(transport=transport, registry=registry)
      self.services_information = dict()
      self._services_lock = threading.Lock()
      # Use the adapter's actual exchange name if available, otherwise generate one
      if registry is not None and hasattr(registry, 'get_update_channel_name'):
         self.realtime_update_exchange = registry.get_update_channel_name() or ('registry_update' + str(uuid.uuid4()))
      else:
         self.realtime_update_exchange = 'registry_update' + str(uuid.uuid4())
      self._alias_dict = {}
      self._health_check_running = False
      self._failure_counts = {}
      try:
         with open(self.ALIAS_CONF_PATH, 'r') as file:
            self._alias_dict = json.load(file)
      except FileNotFoundError:
         logger.debug("Alias config file '%s' not found, using empty alias dict.", self.ALIAS_CONF_PATH)
      except json.JSONDecodeError:
         logger.warning("Alias config file '%s' contains invalid JSON.", self.ALIAS_CONF_PATH)

   def handle_update(self, service_information):
      """
Handle a service registration/unregistration event.

**Arguments:**

* ``service_information``

  / *Condition*: required / *Type*: dict /

  Dict with 'info' and 'state' keys.
      """
      name = service_information['info']['name']
      with self._services_lock:
         if name not in self.services_information and service_information['state'] == "on":
            self.services_information[name] = service_information['info']
            self._failure_counts.pop(name, None)
         elif name in self.services_information and service_information['state'] == "off":
            del self.services_information[name]
            self._failure_counts.pop(name, None)

      logger.info("Received update: %s", service_information)

   def notify_updates(self):
      """
Notify connected clients about service updates via the registry port.
      """
      if self._registry is not None:
         with self._services_lock:
            snapshot = dict(self.services_information)
         self._registry.notify_update(snapshot)

   def _broadcast_shutdown_sentinel(self):
      """
Publish a sentinel to notify subscribers the registry is shutting down.
      """
      if self._registry is not None:
         self._registry.notify_update({"__registry_shutdown__": True})

   def svc_api_shutdown(self):
      """
Gracefully shut down the Service Registry.
      """
      logger.info("ServiceRegistry shutting down — broadcasting shutdown sentinel")
      try:
         self._broadcast_shutdown_sentinel()
      except Exception as ex:
         logger.warning("Failed to broadcast shutdown sentinel: %s", ex)
      return super().svc_api_shutdown()

   def svc_api_get_services_info(self):
      """
Retrieve information of all services connected to the broker.

**Returns:**

  / *Type*: dict /

  A dictionary containing information of all connected services.
      """
      with self._services_lock:
         return json.dumps(self.services_information)

   def svc_api_get_realtime_update_exchange(self):
      """
Retrieve the exchange name of the realtime update exchange.

**Returns:**

  / *Type*: str /

  The name of the realtime update exchange.
      """
      return self.realtime_update_exchange

   def svc_api_update_alias_conf(self, alias_string):
      """
Update the alias configuration information.

**Arguments:**

* ``alias_string``

  / *Condition*: required / *Type*: str /

  The alias configuration string to be updated.

**Returns:**

(*no returns*)
      """
      with open(self.ALIAS_CONF_PATH, 'w') as file:
         file.write(alias_string)

      with open(self.ALIAS_CONF_PATH, 'r') as file:
         self._alias_dict = json.load(file)

   def svc_api_get_alias_conf(self):
      """
Retrieve the alias configuration string in JSON format.

**Returns:**

  / *Type*: str /

  The alias configuration string in JSON format.
      """
      return json.dumps(self._alias_dict)

   def is_specific_request(self, request):
      """
Check if the request is an alias-routed request.
      """
      return request in self._alias_dict

   def on_specific_request(self, request, body):
      """
Handle an alias-routed request by forwarding to the target service.
      """
      return self.handle_alias_request(body)

   def handle_alias_request(self, body):
      """
Handle an alias request by routing to the actual service.

**Arguments:**

* ``body``

  / *Condition*: required / *Type*: dict /

  Dict with 'method' and 'args' keys.

**Returns:**

  / *Type*: ServiceResponse /

  ServiceResponse or raw response dict from the target service.
      """
      service = self._alias_dict[body['method']]["Service name"]
      request_api = self._alias_dict[body['method']]["Method name"]
      result_type = ResultType.FAIL

      try:
         with self._services_lock:
            if service in self.services_information:
               routing_key = self.services_information[service]['routing_key']
            else:
               raise ServiceNotFoundError(f"Service {service} is unavailable!!!")

         alias_args_string = self._alias_dict[body['method']]["Arguments"]
         actual_args_list = body['args']

         if isinstance(actual_args_list, str):
            actual_args_list = [actual_args_list]

         modified_string = alias_args_string.replace("${input}", "{}").format(*actual_args_list)
         args_list = modified_string.split(',')

         request_data = {
            'method': request_api,
            'args': args_list,
         }

         logger.info("Call method %s of '%s' with params %s", request_api, service, args_list)
         resp = self.request_service(request_data, ServiceBase._SERVICE_REQUEST_EXCHANGE, routing_key)
         return resp

      except Exception as ex:
         result_type = ResultType.EXCEPT
         response = str(ex)
         return ServiceResponse(request_api, result_type.value, response)

   # ------------------------------------------------------------------
   # Health check — detect externally-killed services via consumer count
   # ------------------------------------------------------------------

   def run_health_check_loop(self, interval=30, max_failures=2,
                             broker_host='localhost', broker_port=5672):
      """
Blocking loop for a daemon thread.  Periodically checks whether each
registered service still has active RabbitMQ consumers.

**Arguments:**

* ``interval``

  / *Condition*: optional / *Type*: int / *Default*: 30 /

  Seconds between health-check cycles.

* ``max_failures``

  / *Condition*: optional / *Type*: int / *Default*: 2 /

  Consecutive zero-consumer checks before auto-unregister.

* ``broker_host``

  / *Condition*: optional / *Type*: str / *Default*: 'localhost' /

  RabbitMQ broker host for the temporary connection.

* ``broker_port``

  / *Condition*: optional / *Type*: int / *Default*: 5672 /

  RabbitMQ broker port for the temporary connection.
      """
      self._health_check_running = True
      logger.info("Health-check loop started (interval=%ss, max_failures=%s)",
                  interval, max_failures)
      while self._health_check_running:
         try:
            self._run_health_check_cycle(max_failures, broker_host, int(broker_port))
         except Exception:
            logger.warning("Health-check cycle failed", exc_info=True)
         # Sleep in 1-second increments so the thread can stop promptly.
         for _ in range(interval):
            if not self._health_check_running:
               break
            time.sleep(1)
      logger.info("Health-check loop stopped.")

   def _run_health_check_cycle(self, max_failures, broker_host, broker_port):
      """
One health-check cycle: open a temporary pika connection, query
``consumer_count`` for every registered service queue, and auto-unregister
services that have had zero consumers for *max_failures* consecutive checks.

**Arguments:**

* ``max_failures``

  / *Condition*: required / *Type*: int /

  Consecutive zero-consumer checks before auto-unregister.

* ``broker_host``

  / *Condition*: required / *Type*: str /

  RabbitMQ broker host.

* ``broker_port``

  / *Condition*: required / *Type*: int /

  RabbitMQ broker port.
      """
      import pika

      with self._services_lock:
         service_names = [
            name for name in self.services_information
            if name != self._SERVICE_INFO['name']
         ]

      if not service_names:
         return

      connection = pika.BlockingConnection(
         pika.ConnectionParameters(host=broker_host, port=broker_port)
      )
      try:
         channel = connection.channel()
         dead_services = []

         for name in service_names:
            try:
               result = channel.queue_declare(queue=name, passive=True)
               consumer_count = result.method.consumer_count
            except pika.exceptions.ChannelClosedByBroker:
               # Queue does not exist — treat as dead.
               consumer_count = 0
               # Re-open channel after ChannelClosedByBroker.
               channel = connection.channel()

            if consumer_count == 0:
               self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
               logger.debug("Health-check: '%s' has 0 consumers (%s/%s)",
                           name, self._failure_counts[name], max_failures)
            else:
               self._failure_counts.pop(name, None)

            if self._failure_counts.get(name, 0) >= max_failures:
               dead_services.append(name)

         for name in dead_services:
            logger.warning("Auto-unregistering dead service '%s' (0 consumers)", name)
            with self._services_lock:
               info = self.services_information.get(name)
            if info is not None:
               self.handle_update({'info': info, 'state': 'off'})
               self.notify_updates()
            self._failure_counts.pop(name, None)

      finally:
         try:
            connection.close()
         except Exception:
            pass

   def stop_health_check(self):
      """Signal the health-check loop to stop."""
      self._health_check_running = False
