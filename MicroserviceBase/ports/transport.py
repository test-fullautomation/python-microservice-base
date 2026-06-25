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
# File: transport.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Abstract interface for message transport.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

from abc import ABC, abstractmethod


class TransportPort(ABC):
   """
Abstract interface for message transport.

Implementations provide the actual connectivity (e.g., RabbitMQ, Redis, MQTT).
The domain layer depends only on this interface.
   """

   @abstractmethod
   def connect(self):
      """
Establish connection to the message broker.
      """
      ...

   @abstractmethod
   def disconnect(self):
      """
Close connection to the message broker.
      """
      ...

   @abstractmethod
   def stop_consuming(self):
      """
Signal the consume loop to stop.
      """
      ...

   @abstractmethod
   def consume(self, service_name, routing_key, exchange, handler, on_ready=None):
      """
Start consuming messages for a service.

**Arguments:**

* ``service_name``

  / *Condition*: required / *Type*: str /

  Name of the service (used as queue name).

* ``routing_key``

  / *Condition*: required / *Type*: str /

  Routing key to bind the queue.

* ``exchange``

  / *Condition*: required / *Type*: str /

  Exchange name to bind to.

* ``handler``

  / *Condition*: required / *Type*: callable /

  Callback function(ch, method, props, body) for incoming messages.

* ``on_ready``

  / *Condition*: optional / *Type*: callable / *Default*: None /

  Called with no arguments once the queue is bound and consuming has
  started, i.e. once it is safe for a publisher to send messages.
      """
      ...

   @abstractmethod
   def rpc_call(self, request_data, exchange_name, routing_key):
      """
Send an RPC request and wait for the response.

**Arguments:**

* ``request_data``

  / *Condition*: required / *Type*: dict /

  Dict to serialize and send as the request body.

* ``exchange_name``

  / *Condition*: required / *Type*: str /

  Exchange to publish to.

* ``routing_key``

  / *Condition*: required / *Type*: str /

  Routing key for the target service.

**Returns:**

Parsed response dict from the target service.
      """
      ...

   @abstractmethod
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

  Message body.

* ``properties``

  / *Condition*: optional / *Type*: dict /

  Optional message properties dict.
      """
      ...
