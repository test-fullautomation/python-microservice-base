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
# File: ui_bridge.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Abstract interface for UI communication bridge.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

from abc import ABC, abstractmethod


class UIBridgePort(ABC):
   """
Abstract interface for UI communication bridge.

Implementations provide the actual UI connectivity (e.g., FastAPI REST, gRPC).
Any frontend (Electron, browser, mobile) can connect through this port.
   """

   @abstractmethod
   def start(self, request_handler, services_info_provider):
      """
Start the UI bridge server.

**Arguments:**

* ``request_handler``

  / *Condition*: required / *Type*: callable /

  Callable that accepts a ServiceRequest dict and returns
  a ServiceResponse dict. Used to route UI requests to services.

* ``services_info_provider``

  / *Condition*: required / *Type*: callable /

  Callable that returns the current services info dict.
      """
      ...

   @abstractmethod
   def stop(self):
      """
Stop the UI bridge server.
      """
      ...

   @abstractmethod
   def broadcast_update(self, services_info):
      """
Push a services update to all connected UI clients.

**Arguments:**

* ``services_info``

  / *Condition*: required / *Type*: dict /

  Dict of all current service information.
      """
      ...
