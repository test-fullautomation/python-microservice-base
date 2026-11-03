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
# File: rabbitmq_adapter.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   RabbitMQ implementation of the TransportPort interface.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import json
import logging
import os
import signal
import sys
import time
import uuid
import pika

from ...ports.transport import TransportPort
from ...domain.exceptions import TransportError
from ..config.rabbitmq_config import RabbitMQConfig

logger = logging.getLogger(__name__)


class RabbitMQTransportAdapter(TransportPort):
   """
RabbitMQ implementation of the TransportPort interface.
   """

   def __init__(self, config):
      """
Initialize with a RabbitMQConfig.

**Arguments:**

* ``config``

  / *Condition*: required / *Type*: RabbitMQConfig /

  RabbitMQConfig instance.
      """
      self._config = config
      self._connection_params = config.to_connection_params()
      self._connection = None
      self._consume_channel = None
      self._consuming = False

   def connect(self):
      """
Establish connection to RabbitMQ.
      """
      try:
         self._connection = pika.BlockingConnection(
            pika.ConnectionParameters(**self._connection_params)
         )
      except Exception as ex:
         raise TransportError(f"Unable to connect to RabbitMQ broker: {ex}")

   def disconnect(self):
      """
Close connection to RabbitMQ.
      """
      logger.info("disconnect() called (PID=%d)", os.getpid())
      self._consuming = False
      if self._consume_channel is not None:
         try:
            self._consume_channel.stop_consuming()
            if self._consume_channel.is_open:
               self._consume_channel.close()
         except pika.exceptions.AMQPError:
            logger.debug("Error closing consume channel", exc_info=True)
         self._consume_channel = None
      if self._connection is not None and not self._connection.is_closed:
         try:
            self._connection.close()
         except pika.exceptions.AMQPError:
            logger.debug("Error closing RabbitMQ connection", exc_info=True)
         self._connection = None

   @property
   def connection(self):
      """
Access the underlying pika connection (for backward compat).
      """
      return self._connection

   def stop_consuming(self):
      """
Signal the consume loop to exit.
      """
      self._consuming = False

   def consume(self, service_name, routing_key, exchange, handler, on_ready=None):
      """
Start consuming RPC requests for a service.

Sets up the exchange, queue, binding, and starts blocking consumption.

**Arguments:**

* ``service_name``

  / *Condition*: required / *Type*: str /

  Name used as the queue name.

* ``routing_key``

  / *Condition*: required / *Type*: str /

  Routing key for queue binding.

* ``exchange``

  / *Condition*: required / *Type*: str /

  Exchange name to bind to.

* ``handler``

  / *Condition*: required / *Type*: callable /

  Callback function(ch, method, props, body).

* ``on_ready``

  / *Condition*: optional / *Type*: callable / *Default*: None /

  Called with no arguments once the queue is declared, bound and consuming
  has started, i.e. once it is safe for a publisher to send messages that
  this consumer will receive. Useful to avoid the publish-before-bind race
  where a ``direct`` exchange drops unroutable messages.
      """
      if self._connection is None:
         raise TransportError("Not connected. Call connect() first.")

      self._consume_channel = self._connection.channel()
      self._consume_channel.exchange_declare(exchange=exchange, exchange_type='direct')
      self._consume_channel.queue_declare(queue=service_name)
      self._consume_channel.queue_purge(queue=service_name)
      logger.info("Queue '%s' purged", service_name)

      self._consume_channel.queue_bind(
         exchange=exchange,
         queue=service_name,
         routing_key=routing_key,
      )

      self._consume_channel.basic_qos(prefetch_count=1)
      self._consume_channel.basic_consume(queue=service_name, on_message_callback=handler)

      # The queue is now declared, bound and consuming: signal readiness so a
      # publisher can safely send without racing the binding setup.
      if on_ready is not None:
         try:
            on_ready()
         except Exception:
            logger.debug("on_ready callback raised", exc_info=True)

      logger.info("Awaiting RPC requests (interruptible loop, PID=%d)", os.getpid())

      # On Windows, CTRL_BREAK_EVENT raises SIGBREAK whose default handler
      # calls ExitProcess — killing the process without running finally
      # blocks or cleanup code.  Install a handler that raises
      # KeyboardInterrupt instead, so services can unregister gracefully.
      if sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
         try:
            signal.signal(signal.SIGBREAK, signal.default_int_handler)
         except (OSError, ValueError):
            pass  # Not main thread, or signal not supported

      # Use process_data_events with timeout instead of start_consuming()
      # so that KeyboardInterrupt (from CTRL_BREAK_EVENT on Windows or
      # SIGINT on Linux) can be delivered between iterations.
      self._consuming = True
      while self._consuming:
         self._connection.process_data_events(time_limit=1)
      logger.info("Consume loop exited (self._consuming set to False)")

   def rpc_call(self, request_data, exchange_name, routing_key, timeout=30):
      """
Send an RPC request and wait for the response.

Creates a new connection for the RPC call (matching original behavior).

**Arguments:**

* ``request_data``

  / *Condition*: required / *Type*: dict /

  dict to serialize as the request body.

* ``exchange_name``

  / *Condition*: required / *Type*: str /

  Exchange to publish to.

* ``routing_key``

  / *Condition*: required / *Type*: str /

  Routing key for the target service.

* ``timeout``

  / *Condition*: optional / *Type*: int / *Default*: 30 /

  Timeout in seconds for waiting for the response.

**Returns:**

  Parsed response dict.
      """
      params = dict(self._connection_params)
      params['blocked_connection_timeout'] = timeout
      connection = pika.BlockingConnection(
         pika.ConnectionParameters(**params)
      )
      try:
         channel = connection.channel()
         result = channel.queue_declare(queue='', exclusive=True)
         callback_queue = result.method.queue
         correlation_id = str(uuid.uuid4())
         resp = None

         def on_response(ch, method, properties, body):
            if properties.correlation_id == correlation_id:
               nonlocal resp
               resp = json.loads(body.decode())
               logger.debug("Got response: %s", resp)

         channel.basic_consume(
            queue=callback_queue,
            on_message_callback=on_response,
            auto_ack=True,
         )

         logger.info("Requesting Service with data: %s", request_data)
         channel.basic_publish(
            exchange=exchange_name,
            routing_key=routing_key,
            properties=pika.BasicProperties(
               reply_to=callback_queue,
               correlation_id=correlation_id,
            ),
            body=json.dumps(request_data),
         )

         deadline = time.monotonic() + timeout
         while resp is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
               raise TransportError(f"RPC call timed out after {timeout}s")
            connection.process_data_events(time_limit=remaining)

         return resp
      finally:
         if not connection.is_closed:
            connection.close()

   def publish(self, exchange, routing_key, body, properties=None):
      """
Publish a message to an exchange.

**Arguments:**

* ``exchange``

  / *Condition*: required / *Type*: str /

  Exchange name.

* ``routing_key``

  / *Condition*: required / *Type*: str /

  Routing key.

* ``body``

  / *Condition*: required / *Type*: str or bytes /

  Message body (str or bytes).

* ``properties``

  / *Condition*: optional / *Type*: pika.BasicProperties /

  Optional pika.BasicProperties.
      """
      if self._connection is None:
         raise TransportError("Not connected. Call connect() first.")

      channel = self._connection.channel()
      try:
         if properties is None:
            properties = pika.BasicProperties(delivery_mode=2)
         channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body if isinstance(body, bytes) else body.encode('utf-8') if isinstance(body, str) else json.dumps(body),
            properties=properties,
         )
      finally:
         if channel.is_open:
            channel.close()
