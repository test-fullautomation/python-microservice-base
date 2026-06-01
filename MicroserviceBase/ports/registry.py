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
# File: registry.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Abstract interface for service registration and discovery.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

from abc import ABC, abstractmethod


class ServiceRegistryPort(ABC):
   """
Abstract interface for service registration and discovery.

Implementations handle how services announce themselves and
how the registry discovers/tracks them.
   """

   @abstractmethod
   def register(self, service_info):
      """
Register a service with the registry.

**Arguments:**

* ``service_info``

  / *Condition*: required / *Type*: dict /

  Dict containing service metadata.
      """
      ...

   @abstractmethod
   def unregister(self, service_info):
      """
Unregister a service from the registry.

**Arguments:**

* ``service_info``

  / *Condition*: required / *Type*: dict /

  Dict containing service metadata.
      """
      ...

   @abstractmethod
   def subscribe_to_events(self, handler):
      """
Subscribe to service registration/unregistration events.

**Arguments:**

* ``handler``

  / *Condition*: required / *Type*: callable /

  Callback function(ch, method, properties, body) for events.
      """
      ...

   @abstractmethod
   def notify_update(self, services_info):
      """
Broadcast a services update to all subscribers.

**Arguments:**

* ``services_info``

  / *Condition*: required / *Type*: dict /

  Dict of all current service information.
      """
      ...

   @abstractmethod
   def get_update_channel_name(self):
      """
Return the name of the realtime update channel/exchange.

**Returns:**

Channel/exchange name as a string.
      """
      ...
