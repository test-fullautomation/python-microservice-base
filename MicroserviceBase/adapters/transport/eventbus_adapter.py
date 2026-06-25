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
# File: eventbus_adapter.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   EventBusClient implementation of the TransportPort interface.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import json
import logging
import uuid
import threading

from ...ports.transport import TransportPort
from ...domain.exceptions import TransportError
from ..config.eventbus_config import EventBusConfig

logger = logging.getLogger(__name__)


class _ChannelProxy:
   """
Lightweight proxy that mimics a pika channel for the domain handler.

Translates basic_publish and basic_ack calls into EventBusClient operations.
   """

   def __init__(self, client):
      """
Initialize the channel proxy.

**Arguments:**

* ``client``

  / *Condition*: required / *Type*: EventBusClient /

  The EventBusClient instance used for sending replies.
      """
      self._client = client

   def basic_publish(self, exchange, routing_key, properties=None, body=None):
      """
Publish a reply message via the EventBusClient.

**Arguments:**

* ``exchange``

  / *Condition*: required / *Type*: str /

  Exchange name (ignored, EventBusClient uses its configured exchange).

* ``routing_key``

  / *Condition*: required / *Type*: str /

  Routing key for the reply (the reply_to value).

* ``properties``

  / *Condition*: optional / *Type*: object /

  Properties object with correlation_id attribute.

* ``body``

  / *Condition*: optional / *Type*: str or bytes /

  The message body (JSON string or bytes).
      """
      from EventBusClient.message.dict_message import DictMessage

      if isinstance(body, bytes):
         data = json.loads(body.decode('utf-8'))
      elif isinstance(body, str):
         data = json.loads(body)
      else:
         data = body

      headers = {}
      if properties is not None and hasattr(properties, 'correlation_id'):
         headers['correlation_id'] = properties.correlation_id

      self._client.send_sync(routing_key, DictMessage(data), headers=headers)

   def basic_ack(self, delivery_tag=None):
      """
Acknowledge a message (no-op for EventBusClient which auto-acks).
      """
      pass


class _MethodProxy:
   """
Lightweight proxy that mimics a pika method frame.
   """

   def __init__(self, delivery_tag=0):
      """
Initialize the method proxy.

**Arguments:**

* ``delivery_tag``

  / *Condition*: optional / *Type*: int / *Default*: 0 /

  The delivery tag (unused with EventBusClient).
      """
      self.delivery_tag = delivery_tag


class _PropertiesProxy:
   """
Lightweight proxy that mimics pika BasicProperties.
   """

   def __init__(self, reply_to=None, correlation_id=None):
      """
Initialize the properties proxy.

**Arguments:**

* ``reply_to``

  / *Condition*: optional / *Type*: str /

  The reply routing key.

* ``correlation_id``

  / *Condition*: optional / *Type*: str /

  The correlation ID.
      """
      self.reply_to = reply_to
      self.correlation_id = correlation_id

   def __call__(self, correlation_id=None):
      """
Callable to mimic type(props)(correlation_id=...) pattern used by domain handler.
      """
      return _PropertiesProxy(
         reply_to=self.reply_to,
         correlation_id=correlation_id,
      )


class EventBusTransportAdapter(TransportPort):
   """
EventBusClient implementation of the TransportPort interface.

Creates the underlying EventBusClient from a JSONP configuration file
via ``EventBusClient.from_config_sync()``.
   """

   def __init__(self, config):
      """
Initialize with an EventBusConfig.

**Arguments:**

* ``config``

  / *Condition*: required / *Type*: EventBusConfig /

  EventBusConfig instance holding the JSONP config file path.
      """
      self._config = config
      self._client = None
      self._stop_event = threading.Event()

   def connect(self):
      """
Create the EventBusClient from the JSONP config and establish connection.
      """
      try:
         from EventBusClient.event_bus_client import EventBusClient

         self._client = EventBusClient.from_config_sync(
            config_path=self._config.config_path,
         )
         self._client.start_background_loop()
         self._client.connect_sync()
      except Exception as ex:
         raise TransportError(f"Unable to connect via EventBusClient: {ex}")

   def disconnect(self):
      """
Close the EventBusClient connection.
      """
      self._stop_event.set()
      if self._client is not None:
         try:
            self._client.close_sync()
         except ConnectionError:
            logger.debug("Error closing EventBusClient connection", exc_info=True)
         self._client = None

   def consume(self, service_name, routing_key, exchange, handler, on_ready=None):
      """
Start consuming RPC requests for a service.

Subscribes to the routing key and blocks the calling thread.
Incoming messages are adapted to the pika-style handler signature.

**Arguments:**

* ``service_name``

  / *Condition*: required / *Type*: str /

  Name used as the service identifier.

* ``routing_key``

  / *Condition*: required / *Type*: str /

  Routing key for message binding.

* ``exchange``

  / *Condition*: required / *Type*: str /

  Exchange name (must match the configured exchange).

* ``handler``

  / *Condition*: required / *Type*: callable /

  Callback function(ch, method, props, body).

* ``on_ready``

  / *Condition*: optional / *Type*: callable / *Default*: None /

  Called with no arguments once the subscription is registered, i.e. once
  it is safe for a publisher to send messages that this consumer will
  receive.
      """
      if self._client is None:
         raise TransportError("Not connected. Call connect() first.")

      from EventBusClient.message.dict_message import DictMessage

      ch_proxy = _ChannelProxy(self._client)

      def _on_message(message, headers):
         body = message.get_value()
         reply_to = headers.get('reply_to', '')
         correlation_id = headers.get('correlation_id', '')
         method_proxy = _MethodProxy()
         props_proxy = _PropertiesProxy(
            reply_to=reply_to,
            correlation_id=correlation_id,
         )
         handler(ch_proxy, method_proxy, props_proxy, body)

      self._client.on_sync(routing_key, DictMessage, _on_message)
      logger.info("Awaiting RPC requests via EventBusClient")

      # The subscription is registered: signal readiness so a publisher can
      # safely send without racing the subscription setup.
      if on_ready is not None:
         try:
            on_ready()
         except Exception:
            logger.warning("on_ready callback raised", exc_info=True)

      self._stop_event.clear()
      self._stop_event.wait()

   def rpc_call(self, request_data, exchange_name, routing_key):
      """
Send an RPC request and wait for the response.

Creates a temporary subscription for the reply, sends the request
with reply_to and correlation_id headers, and waits for the response.

**Arguments:**

* ``request_data``

  / *Condition*: required / *Type*: dict /

  dict to send as the request body.

* ``exchange_name``

  / *Condition*: required / *Type*: str /

  Exchange to publish to (must match configured exchange).

* ``routing_key``

  / *Condition*: required / *Type*: str /

  Routing key for the target service.

**Returns:**

  Parsed response dict.
      """
      if self._client is None:
         raise TransportError("Not connected. Call connect() first.")

      from EventBusClient.message.dict_message import DictMessage

      correlation_id = str(uuid.uuid4())
      reply_key = f"reply.{correlation_id}"

      cache = self._client.on_sync(reply_key, DictMessage)

      headers = {
         'reply_to': reply_key,
         'correlation_id': correlation_id,
      }

      logger.info("Requesting Service with data: %s", request_data)
      self._client.send_sync(routing_key, DictMessage(request_data), headers=headers)

      response_msg = cache.get(timeout=30)
      resp = response_msg.get_value()

      self._client.off_sync(reply_key)

      logger.debug("Got response: %s", resp)
      return resp

   def publish(self, exchange, routing_key, body, properties=None):
      """
Publish a message to the exchange.

**Arguments:**

* ``exchange``

  / *Condition*: required / *Type*: str /

  Exchange name (must match configured exchange).

* ``routing_key``

  / *Condition*: required / *Type*: str /

  Routing key.

* ``body``

  / *Condition*: required / *Type*: str, bytes, or dict /

  Message body.

* ``properties``

  / *Condition*: optional / *Type*: dict /

  Optional message properties (used for headers).
      """
      if self._client is None:
         raise TransportError("Not connected. Call connect() first.")

      from EventBusClient.message.dict_message import DictMessage

      if isinstance(body, bytes):
         data = json.loads(body.decode('utf-8'))
      elif isinstance(body, str):
         data = json.loads(body)
      else:
         data = body

      headers = {}
      if properties is not None:
         if hasattr(properties, 'correlation_id') and properties.correlation_id:
            headers['correlation_id'] = properties.correlation_id
         if hasattr(properties, 'reply_to') and properties.reply_to:
            headers['reply_to'] = properties.reply_to

      self._client.send_sync(routing_key, DictMessage(data), headers=headers)
