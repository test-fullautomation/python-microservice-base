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
# File: eventbus_registry_adapter.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   EventBusClient implementation of the ServiceRegistryPort interface.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import json
import logging

from ...ports.registry import ServiceRegistryPort
from ..config.eventbus_config import EventBusConfig

logger = logging.getLogger(__name__)


class EventBusRegistryAdapter(ServiceRegistryPort):
   """
EventBusClient implementation of the ServiceRegistryPort interface.

Uses EventBusClient with TopicExchangeHandler for service registration events
and a FanoutExchangeHandler for realtime update broadcasts.

Both clients are created from the same JSONP config with exchange overrides
via ``EventBusConfig.to_config_source()``.
   """

   EXCHANGE_NAME = 'service_information'
   ROUTING_KEY = 'service.information'

   def __init__(self, config, update_exchange_name=None):
      """
Initialize with an EventBusConfig.

**Arguments:**

* ``config``

  / *Condition*: required / *Type*: EventBusConfig /

  EventBusConfig instance holding the JSONP config file path.

* ``update_exchange_name``

  / *Condition*: optional / *Type*: str /

  Name for the realtime update fanout exchange.
  If None, no update broadcasting is done.
      """
      self._config = config
      self._update_exchange_name = update_exchange_name
      self._registry_client = None
      self._update_client = None

   def _get_registry_client(self):
      """
Create or return the EventBusClient for the registry topic exchange.

Uses the base JSONP config with exchange_name overridden to
the service_information exchange.
      """
      if self._registry_client is None:
         from EventBusClient.event_bus_client import EventBusClient

         config_source = self._config.to_config_source(
            exchange_name=self.EXCHANGE_NAME,
            exchange_handler='TopicExchangeHandler',
         )
         self._registry_client = EventBusClient.from_config_sync(
            config_source=config_source,
         )
         self._registry_client.start_background_loop()
         self._registry_client.connect_sync()
      return self._registry_client

   def _get_update_client(self):
      """
Create or return the EventBusClient for the update fanout exchange.

Uses the base JSONP config with exchange_handler overridden to
FanoutExchangeHandler and exchange_name set to the update exchange.
      """
      if self._update_client is None and self._update_exchange_name is not None:
         from EventBusClient.event_bus_client import EventBusClient

         config_source = self._config.to_config_source(
            exchange_name=self._update_exchange_name,
            exchange_handler='FanoutExchangeHandler',
         )
         self._update_client = EventBusClient.from_config_sync(
            config_source=config_source,
         )
         self._update_client.start_background_loop()
         self._update_client.connect_sync()
      return self._update_client

   def register(self, service_info):
      """
Register a service by publishing to the service_information exchange.

**Arguments:**

* ``service_info``

  / *Condition*: required / *Type*: dict /

  dict containing service metadata.
      """
      self._publish_service_event(service_info, state='on')
      logger.info("Registered service to Registry Service")

   def unregister(self, service_info):
      """
Unregister a service by publishing to the service_information exchange.

**Arguments:**

* ``service_info``

  / *Condition*: required / *Type*: dict /

  dict containing service metadata.
      """
      self._publish_service_event(service_info, state='off')
      logger.info("Unregistered service from Registry Service")

   def _publish_service_event(self, service_info, state):
      """
Publish a service registration/unregistration event.

**Arguments:**

* ``service_info``

  / *Condition*: required / *Type*: dict /

  dict containing service metadata.

* ``state``

  / *Condition*: required / *Type*: str /

  'on' or 'off'.
      """
      from EventBusClient.message.dict_message import DictMessage

      event_body = {
         'info': service_info,
         'state': state,
      }
      client = self._get_registry_client()
      client.send_sync(self.ROUTING_KEY, DictMessage(event_body))

   def subscribe_to_events(self, handler):
      """
Subscribe to service registration events.

Blocks the calling thread. Typically called from a daemon thread.
The handler receives the pika-style callback signature
(ch, method, properties, body) for backward compatibility.

**Arguments:**

* ``handler``

  / *Condition*: required / *Type*: callable /

  Callback function(ch, method, properties, body).
      """
      import threading
      from EventBusClient.message.dict_message import DictMessage

      client = self._get_registry_client()

      def _on_event(message, headers):
         body = json.dumps(message.get_value()).encode('utf-8')
         handler(None, None, None, body)

      client.on_sync(self.ROUTING_KEY, DictMessage, _on_event)
      logger.info("Waiting for updates. To exit press CTRL+C")

      stop_event = threading.Event()
      stop_event.wait()

   def notify_update(self, services_info):
      """
Broadcast services update to the realtime update fanout exchange.

**Arguments:**

* ``services_info``

  / *Condition*: required / *Type*: dict /

  dict of all current service information.
      """
      if self._update_exchange_name is None:
         return

      from EventBusClient.message.dict_message import DictMessage

      client = self._get_update_client()
      if client is not None:
         client.send_sync('', DictMessage(services_info))
         logger.info("Update info sent via EventBusClient")

   def get_update_channel_name(self):
      """
Return the realtime update exchange name.
      """
      return self._update_exchange_name

   def cleanup(self):
      """
Close all EventBusClient connections.
      """
      if self._registry_client is not None:
         try:
            self._registry_client.close_sync()
         except ConnectionError:
            logger.debug("Error closing registry client", exc_info=True)
         self._registry_client = None
      if self._update_client is not None:
         try:
            self._update_client.close_sync()
         except ConnectionError:
            logger.debug("Error closing update client", exc_info=True)
         self._update_client = None
