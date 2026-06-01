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
# File: eventbus_config.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Configuration dataclass for EventBusClient-based adapters.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

from dataclasses import dataclass


@dataclass
class EventBusConfig:
   """
Configuration for EventBusClient-based adapters.

Wraps a JSONP config file path used by EventBusClient.from_config_sync().
   """
   config_path: str = None

   def load_config(self):
      """
Load and return the parsed config as a dict.

Requires EventBusClient to be installed.

**Returns:**

  / *Type*: dict /

  Parsed configuration dictionary.
      """
      from EventBusClient.plugin_loader import PluginLoader
      return dict(PluginLoader.load_config(self.config_path))

   def to_config_source(self, **overrides):
      """
Load config and return as a dict with optional field overrides.

Useful for creating derivative clients (e.g., registry or fanout)
that share connection settings but differ in exchange configuration.

**Arguments:**

* ``overrides``

  / *Condition*: optional / *Type*: keyword arguments /

  Fields to override in the loaded config (e.g., exchange_name, exchange_handler).

**Returns:**

  / *Type*: dict /

  Config dictionary with overrides applied.
      """
      config = self.load_config()
      config.update(overrides)
      return config
