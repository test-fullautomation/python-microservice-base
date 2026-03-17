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
# File: hub_manager.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Mar 2026.
#
# Description:
#
#   Abstract interface for process/job orchestration backends.
#   Implemented by LocalHubManager (local processes) and NomadHubAdapter
#   (HashiCorp Nomad jobs).
#
# History:
#
# 12.03.2026 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

from abc import ABC, abstractmethod


class HubManagerPort(ABC):
   """
Abstract interface for process/job orchestration backends.

Implementations manage service lifecycles through different backends:
- LocalHubManager: local OS processes via ProcessHub
- NomadHubAdapter: Nomad jobs via HTTP API
   """

   @abstractmethod
   def start_hub(self, mode='standalone', **kwargs):
      """
Start the orchestration backend.

**Arguments:**

* ``mode``

  / *Condition*: optional / *Type*: str / *Default*: 'standalone' /

  Operating mode. Backend-specific values.

**Returns:**

* ``dict`` with at least ``{"status": str}``
      """
      ...

   @abstractmethod
   def stop_hub(self):
      """
Stop the orchestration backend and release resources.

**Returns:**

* ``dict`` with at least ``{"status": str}``
      """
      ...

   @abstractmethod
   def get_status(self):
      """
Get a status snapshot of all managed services/jobs.

**Returns:**

* ``dict`` containing ``running``, ``mode``, ``processes`` list, etc.
      """
      ...

   @abstractmethod
   def start_processes(self, names):
      """
Start named services/jobs.

**Arguments:**

* ``names``

  / *Condition*: required / *Type*: list[str] /

  List of service/process names to start.

**Returns:**

* ``dict`` mapping name to ``{"success": bool, "message": str}``
      """
      ...

   @abstractmethod
   def stop_processes(self, names, force=False):
      """
Stop named services/jobs.

**Arguments:**

* ``names``

  / *Condition*: required / *Type*: list[str] /

  List of service/process names to stop.

* ``force``

  / *Condition*: optional / *Type*: bool / *Default*: False /

  Skip graceful shutdown and force-kill immediately.

**Returns:**

* ``dict`` mapping name to ``{"success": bool, "message": str}``
      """
      ...

   @abstractmethod
   def get_config(self):
      """
Get all service/job configurations.

**Returns:**

* ``dict`` of process/job configs keyed by name.
      """
      ...

   @abstractmethod
   def add_config(self, name, config):
      """
Add a new service/job configuration.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

* ``config``

  / *Condition*: required / *Type*: dict /

**Returns:**

* ``dict`` with ``{"success": bool, "message": str}``
      """
      ...

   @abstractmethod
   def update_config(self, name, config):
      """
Update an existing service/job configuration.

**Returns:**

* ``dict`` with ``{"success": bool, "message": str}``
      """
      ...

   @abstractmethod
   def remove_config(self, name):
      """
Remove a service/job configuration.

**Returns:**

* ``dict`` with ``{"success": bool, "message": str}``
      """
      ...

   @abstractmethod
   def get_service_log(self, name, tail=100):
      """
Read service/job log output.

**Returns:**

* ``dict`` with ``{"name": str, "log": str}``
      """
      ...

   @abstractmethod
   def import_service(self, name, source_path='', zip_data='',
                      wait_time=1.0):
      """
Import a service package.

**Returns:**

* ``dict`` with ``{"success": bool, "message": str}``
      """
      ...

   @abstractmethod
   def remove_service(self, name):
      """
Remove a service entirely (stop + delete config + files).

**Returns:**

* ``dict`` with ``{"success": bool, "message": str}``
      """
      ...

   @abstractmethod
   def reset(self):
      """
Reset the hub — stop all services and clear state.

**Returns:**

* ``dict`` with ``{"success": bool, "message": str}``
      """
      ...
