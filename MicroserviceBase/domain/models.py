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
# File: models.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Domain model dataclasses for service metadata, methods and arguments.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MethodArgument:
   """
Describes a single argument of a service API method.
   """
   name: str
   condition: Optional[str] = None
   type: Optional[str] = None
   default: Optional[str] = None
   description: str = ""

   def to_dict(self):
      """
Converts this ``MethodArgument`` instance to a dictionary.

**Returns:**

  / *Type*: dict /

  Dictionary representation of this argument.
      """
      return {
         'name': self.name,
         'condition': self.condition,
         'type': self.type,
         'default': self.default,
         'description': self.description,
      }

   @classmethod
   def from_dict(cls, data):
      """
Creates a ``MethodArgument`` instance from a dictionary.

**Arguments:**

* ``data``

  / *Condition*: required / *Type*: dict /

  Dictionary containing argument fields.

**Returns:**

  / *Type*: MethodArgument /

  New instance populated from the dictionary.
      """
      return cls(
         name=data.get('name', ''),
         condition=data.get('condition'),
         type=data.get('type'),
         default=data.get('default'),
         description=data.get('description', ''),
      )


@dataclass
class ServiceMethod:
   """
Describes a single API method exposed by a service.
   """
   name: str
   arguments: List[MethodArgument] = field(default_factory=list)
   return_type: Optional[str] = None

   def to_dict(self):
      """
Converts this ``ServiceMethod`` instance to a dictionary.

**Returns:**

  / *Type*: dict /

  Dictionary representation of this method.
      """
      result = {
         'arguments': [arg.to_dict() for arg in self.arguments],
      }
      if self.return_type:
         result['return_type'] = self.return_type
      return result

   @classmethod
   def from_dict(cls, name, data):
      """
Creates a ``ServiceMethod`` instance from a name and dictionary.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  The method name.

* ``data``

  / *Condition*: required / *Type*: dict /

  Dictionary containing method fields.

**Returns:**

  / *Type*: ServiceMethod /

  New instance populated from the dictionary.
      """
      arguments = [
         MethodArgument.from_dict(a) for a in data.get('arguments', [])
      ]
      return cls(
         name=name,
         arguments=arguments,
         return_type=data.get('return_type'),
      )


@dataclass
class ServiceInfo:
   """
Describes a service and its metadata.
   """
   name: str
   description: str = ""
   shortdesc: str = ""
   group: str = ""
   tag: str = ""
   version: str = "1.0.0"
   routing_key: str = ""
   gui_support: bool = False
   downloadable: bool = False
   methods: List[str] = field(default_factory=list)
   methods_info: dict = field(default_factory=dict)

   def to_dict(self):
      """
Converts this ``ServiceInfo`` instance to a dictionary.

**Returns:**

  / *Type*: dict /

  Dictionary representation of this service info.
      """
      methods_info_dict = {}
      for method_name, method in self.methods_info.items():
         if isinstance(method, ServiceMethod):
            methods_info_dict[method_name] = method.to_dict()
         else:
            methods_info_dict[method_name] = method
      return {
         'name': self.name,
         'description': self.description,
         'shortdesc': self.shortdesc,
         'group': self.group,
         'tag': self.tag,
         'version': self.version,
         'routing_key': self.routing_key,
         'gui_support': self.gui_support,
         'downloadable': self.downloadable,
         'methods': list(self.methods),
         'methods_info': methods_info_dict,
      }

   @classmethod
   def from_dict(cls, data):
      """
Creates a ``ServiceInfo`` instance from a dictionary.

**Arguments:**

* ``data``

  / *Condition*: required / *Type*: dict /

  Dictionary containing service info fields.

**Returns:**

  / *Type*: ServiceInfo /

  New instance populated from the dictionary.
      """
      return cls(
         name=data.get('name', ''),
         description=data.get('description', ''),
         shortdesc=data.get('shortdesc', ''),
         group=data.get('group', ''),
         tag=data.get('tag', ''),
         version=data.get('version', '1.0.0'),
         routing_key=data.get('routing_key', ''),
         gui_support=data.get('gui_support', False),
         downloadable=data.get('downloadable', False),
         methods=data.get('methods', []),
         methods_info=data.get('methods_info', {}),
      )
