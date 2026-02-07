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
# File: factory.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Composition root: wires ports to adapter implementations based on config.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

from .adapters.config.rabbitmq_config import RabbitMQConfig
from .adapters.config.eventbus_config import EventBusConfig
from .adapters.transport.rabbitmq_adapter import RabbitMQTransportAdapter
from .adapters.transport.eventbus_adapter import EventBusTransportAdapter
from .adapters.registry.amqp_registry_adapter import AMQPRegistryAdapter
from .adapters.registry.eventbus_registry_adapter import EventBusRegistryAdapter


def create_transport(transport_type='rabbitmq', cmd_args=None, service_name='Service',
                     config_path=None):
   """
Create a TransportPort implementation.

**Arguments:**

* ``transport_type``

  / *Condition*: optional / *Type*: str /

  Transport backend identifier. Supports 'rabbitmq' and 'eventbus'.

* ``cmd_args``

  / *Condition*: optional / *Type*: list /

  Command-line arguments for config parsing (used by 'rabbitmq').

* ``service_name``

  / *Condition*: optional / *Type*: str /

  Service name for help text (used by 'rabbitmq').

* ``config_path``

  / *Condition*: optional / *Type*: str /

  Path to JSONP config file (used by 'eventbus').

**Returns:**

  / *Type*: TransportPort /

  A connected TransportPort instance.
   """
   if transport_type == 'rabbitmq':
      config = RabbitMQConfig.from_cmd_args(cmd_args, service_name=service_name)
      adapter = RabbitMQTransportAdapter(config)
      adapter.connect()
      return adapter
   elif transport_type == 'eventbus':
      config = EventBusConfig(config_path=config_path)
      adapter = EventBusTransportAdapter(config)
      adapter.connect()
      return adapter
   else:
      raise ValueError(f"Unknown transport type: {transport_type}")


def create_registry(transport_type='rabbitmq', cmd_args=None, service_name='Service',
                    update_exchange_name=None, config_path=None):
   """
Create a ServiceRegistryPort implementation.

**Arguments:**

* ``transport_type``

  / *Condition*: optional / *Type*: str /

  Transport backend identifier. Supports 'rabbitmq' and 'eventbus'.

* ``cmd_args``

  / *Condition*: optional / *Type*: list /

  Command-line arguments for config parsing (used by 'rabbitmq').

* ``service_name``

  / *Condition*: optional / *Type*: str /

  Service name for help text (used by 'rabbitmq').

* ``update_exchange_name``

  / *Condition*: optional / *Type*: str /

  Name for the realtime update fanout exchange.

* ``config_path``

  / *Condition*: optional / *Type*: str /

  Path to JSONP config file (used by 'eventbus').

**Returns:**

  / *Type*: ServiceRegistryPort /

  A ServiceRegistryPort instance.
   """
   if transport_type == 'rabbitmq':
      config = RabbitMQConfig.from_cmd_args(cmd_args, service_name=service_name)
      return AMQPRegistryAdapter(config, update_exchange_name=update_exchange_name)
   elif transport_type == 'eventbus':
      config = EventBusConfig(config_path=config_path)
      return EventBusRegistryAdapter(config, update_exchange_name=update_exchange_name)
   else:
      raise ValueError(f"Unknown transport type: {transport_type}")


def create_ui_bridge(bridge_type='fastapi', host='localhost', port=8000):
   """
Create a UIBridgePort implementation.

**Arguments:**

* ``bridge_type``

  / *Condition*: optional / *Type*: str /

  Bridge backend identifier. Currently supports 'fastapi'.

* ``host``

  / *Condition*: optional / *Type*: str /

  Host to bind to.

* ``port``

  / *Condition*: optional / *Type*: int /

  Port to bind to.

**Returns:**

  / *Type*: UIBridgePort /

  A UIBridgePort instance (not yet started).
   """
   if bridge_type == 'fastapi':
      from .adapters.ui_bridge.fastapi_bridge import FastAPIBridge
      return FastAPIBridge(host=host, port=port)
   else:
      raise ValueError(f"Unknown UI bridge type: {bridge_type}")
