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
# File: amqp_registry_adapter.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   AMQP implementation of the ServiceRegistryPort interface.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import json
import logging
import pika

from ...ports.registry import ServiceRegistryPort
from ..config.rabbitmq_config import RabbitMQConfig

logger = logging.getLogger(__name__)


class AMQPRegistryAdapter(ServiceRegistryPort):
   """
AMQP implementation of the ServiceRegistryPort interface.

Uses RabbitMQ topic exchange for service registration events
and fanout exchange for realtime update broadcasts.
   """

   EXCHANGE_NAME = 'service_information'
   QUEUE_NAME = 'service_infor_queue'
   ROUTING_KEY = 'service.information'

   def __init__(self, config, update_exchange_name=None):
      """
Initialize with a RabbitMQConfig.

**Arguments:**

* ``config``

  / *Condition*: required / *Type*: RabbitMQConfig /

  RabbitMQConfig instance.

* ``update_exchange_name``

  / *Condition*: optional / *Type*: str /

  Name for the realtime update fanout exchange.
  If None, no update broadcasting is done.
      """
      self._config = config
      self._connection_params = config.to_connection_params()
      self._update_exchange_name = update_exchange_name
      self._event_connection = None
      self._event_channel = None
      self._event_consuming = False

   def _get_connection(self):
      """
Create a new blocking connection.
      """
      return pika.BlockingConnection(
         pika.ConnectionParameters(**self._connection_params)
      )

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
      connection = self._get_connection()
      try:
         channel = connection.channel()
         channel.exchange_declare(exchange=self.EXCHANGE_NAME, exchange_type='topic')

         event_body = {
            'info': service_info,
            'state': state,
         }

         channel.queue_declare(queue=self.QUEUE_NAME, durable=True)
         channel.queue_bind(
            exchange=self.EXCHANGE_NAME,
            queue=self.QUEUE_NAME,
            routing_key=self.ROUTING_KEY,
         )

         channel.basic_publish(
            exchange=self.EXCHANGE_NAME,
            routing_key=self.ROUTING_KEY,
            body=json.dumps(event_body),
            properties=pika.BasicProperties(delivery_mode=2),
         )
      finally:
         if not connection.is_closed:
            connection.close()

   def subscribe_to_events(self, handler):
      """
Subscribe to service registration events.

Runs in the calling thread (blocking). Typically called from a daemon thread.

**Arguments:**

* ``handler``

  / *Condition*: required / *Type*: callable /

  Callback function(ch, method, properties, body).
      """
      self._event_connection = self._get_connection()
      self._event_channel = self._event_connection.channel()

      self._event_channel.exchange_declare(exchange=self.EXCHANGE_NAME, exchange_type='topic')
      self._event_channel.queue_declare(queue=self.QUEUE_NAME, durable=True)
      self._event_channel.queue_bind(
         exchange=self.EXCHANGE_NAME,
         queue=self.QUEUE_NAME,
         routing_key=self.ROUTING_KEY,
      )

      logger.info("Waiting for updates. To exit press CTRL+C")
      self._event_channel.basic_consume(
         queue=self.QUEUE_NAME,
         on_message_callback=handler,
         auto_ack=True,
      )
      self._event_consuming = True
      try:
         self._event_channel.start_consuming()
      finally:
         self._event_consuming = False

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

      connection = self._get_connection()
      try:
         channel = connection.channel()
         channel.exchange_declare(
            exchange=self._update_exchange_name,
            exchange_type='fanout',
         )

         update_info = json.dumps(services_info)
         channel.basic_publish(
            exchange=self._update_exchange_name,
            routing_key='',
            body=update_info,
         )

         logger.info("Update info sent to RabbitMQ")
      finally:
         if not connection.is_closed:
            connection.close()

   def subscribe_to_updates(self, handler):
      """
Subscribe to the realtime update fanout exchange.

Unlike ``subscribe_to_events`` (which listens for individual on/off events),
this subscribes to the full services dict broadcast by the Registry after
each change. Uses an exclusive temporary queue to avoid competing consumers.

Runs in the calling thread (blocking). Typically called from a daemon thread.

**Arguments:**

* ``handler``

  / *Condition*: required / *Type*: callable /

  Callback function(services_info_dict) called with the full services dict.
      """
      if self._update_exchange_name is None:
         logger.warning("No update exchange configured, cannot subscribe to updates.")
         return

      connection = self._get_connection()
      channel = connection.channel()
      channel.exchange_declare(
         exchange=self._update_exchange_name,
         exchange_type='fanout',
      )
      result = channel.queue_declare(queue='', exclusive=True)
      queue_name = result.method.queue
      channel.queue_bind(exchange=self._update_exchange_name, queue=queue_name)

      def _on_message(ch, method, properties, body):
         try:
            data = json.loads(body.decode('utf-8')) if isinstance(body, bytes) else body
            handler(data)
         except Exception:
            logger.error("Error in update handler", exc_info=True)

      logger.info("Subscribed to update exchange '%s' via queue '%s'",
                   self._update_exchange_name, queue_name)
      channel.basic_consume(queue=queue_name, on_message_callback=_on_message, auto_ack=True)
      channel.start_consuming()

   def get_update_channel_name(self):
      """
Return the realtime update exchange name.
      """
      return self._update_exchange_name

   def cleanup_update_exchange(self):
      """
Delete the realtime update exchange (for cleanup on shutdown).
      """
      if self._update_exchange_name is None:
         return

      connection = None
      try:
         connection = self._get_connection()
         channel = connection.channel()
         channel.exchange_delete(exchange=self._update_exchange_name)
      except pika.exceptions.AMQPError:
         logger.debug("Error cleaning up update exchange", exc_info=True)
      finally:
         if connection is not None and not connection.is_closed:
            connection.close()

   def cleanup(self):
      """
Close event subscription resources and clean up the update exchange.

The event connection may be running ``start_consuming()`` on a different
thread (see ``subscribe_to_events``). pika's ``BlockingConnection`` is not
thread-safe, so stopping/closing it must be scheduled onto the connection's
own I/O thread via ``add_callback_threadsafe`` instead of being called
directly from here. Calling ``stop_consuming``/``close`` cross-thread races
the consuming thread on the same socket and triggers pika internal
assertions (e.g. ``_tx_buffers is empty``).
      """
      connection = self._event_connection
      channel = self._event_channel
      consuming = self._event_consuming
      self._event_channel = None
      self._event_connection = None
      self._event_consuming = False

      if connection is not None:
         def _close():
            try:
               if channel is not None and channel.is_open:
                  channel.stop_consuming()
                  channel.close()
            except pika.exceptions.AMQPError:
               logger.debug("Error closing event channel", exc_info=True)
            try:
               if not connection.is_closed:
                  connection.close()
            except pika.exceptions.AMQPError:
               logger.debug("Error closing event connection", exc_info=True)

         if consuming:
            # Another thread is blocked in start_consuming(); the connection's
            # I/O loop is live there. Schedule the close onto that thread so we
            # don't drive the same socket from two threads (which trips pika
            # internal assertions). This also wakes start_consuming() so the
            # consuming thread unblocks and exits.
            try:
               connection.add_callback_threadsafe(_close)
            except (pika.exceptions.AMQPError, AssertionError):
               logger.debug("Could not schedule threadsafe close, closing directly",
                            exc_info=True)
               _close()
         else:
            # No I/O loop running: it is safe (and necessary) to close directly,
            # otherwise a threadsafe callback would never fire.
            _close()

      self.cleanup_update_exchange()
