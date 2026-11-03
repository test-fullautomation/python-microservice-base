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
# File: messages.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Domain message dataclasses for service requests, responses and events.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import json
import collections
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, List


class ResultType(Enum):
   """
Result types for service responses.
   """
   PASS = "pass"
   FAIL = "fail"
   EXCEPT = "exception"


@dataclass
class ServiceRequest:
   """
Structured request to a service method.
   """
   method: str
   args: Optional[List[Any]] = None

   def to_dict(self):
      """
Converts this ``ServiceRequest`` instance to a dictionary.

**Returns:**

  / *Type*: dict /

  Dictionary representation of this request.
      """
      return {
         'method': self.method,
         'args': self.args,
      }

   def to_json(self):
      """
Converts this ``ServiceRequest`` instance to a JSON string.

**Returns:**

  / *Type*: str /

  JSON string representation of this request.
      """
      return json.dumps(self.to_dict())

   @classmethod
   def from_dict(cls, data):
      """
Creates a ``ServiceRequest`` instance from a dictionary.

**Arguments:**

* ``data``

  / *Condition*: required / *Type*: dict /

  Dictionary containing request fields.

**Returns:**

  / *Type*: ServiceRequest /

  New instance populated from the dictionary.
      """
      return cls(
         method=data.get('method', ''),
         args=data.get('args'),
      )

   @classmethod
   def from_json(cls, json_str):
      """
Creates a ``ServiceRequest`` instance from a JSON string.

**Arguments:**

* ``json_str``

  / *Condition*: required / *Type*: str /

  JSON string containing request fields.

**Returns:**

  / *Type*: ServiceRequest /

  New instance populated from the JSON string.
      """
      return cls.from_dict(json.loads(json_str))


@dataclass
class ServiceResponse:
   """
Structured response from a service method.
   """
   request: str = ""
   result: str = ResultType.PASS.value
   result_data: Any = ""

   def to_dict(self):
      """
Converts this ``ServiceResponse`` instance to an ordered dictionary.

**Returns:**

  / *Type*: OrderedDict /

  Sorted ordered dictionary representation of this response.
      """
      return collections.OrderedDict(sorted({
         'request': self.request,
         'result': self.result if isinstance(self.result, str) else self.result.value,
         'result_data': self.result_data,
      }.items()))

   def to_json(self):
      """
Converts this ``ServiceResponse`` instance to a JSON string.

**Returns:**

  / *Type*: str /

  JSON string representation of this response.
      """
      return json.dumps(self.to_dict())

   def get_json(self):
      """
Backward-compatible alias for ``to_json()``.

**Returns:**

  / *Type*: str /

  JSON string representation of this response.
      """
      return self.to_json()

   def get_data(self):
      """
Backward-compatible alias for ``result_data``.

**Returns:**

  / *Type*: Any /

  The result data of this response.
      """
      return self.result_data

   @classmethod
   def from_dict(cls, data):
      """
Creates a ``ServiceResponse`` instance from a dictionary.

**Arguments:**

* ``data``

  / *Condition*: required / *Type*: dict /

  Dictionary containing response fields.

**Returns:**

  / *Type*: ServiceResponse /

  New instance populated from the dictionary.
      """
      return cls(
         request=data.get('request', ''),
         result=data.get('result', ResultType.PASS.value),
         result_data=data.get('result_data', ''),
      )

   @classmethod
   def from_json(cls, json_str):
      """
Creates a ``ServiceResponse`` instance from a JSON string.

**Arguments:**

* ``json_str``

  / *Condition*: required / *Type*: str /

  JSON string containing response fields.

**Returns:**

  / *Type*: ServiceResponse /

  New instance populated from the JSON string.
      """
      return cls.from_dict(json.loads(json_str))


@dataclass
class ServiceEvent:
   """
Event emitted when service state changes.
   """
   service_name: str
   state: str
   info: dict = field(default_factory=dict)

   def to_dict(self):
      """
Converts this ``ServiceEvent`` instance to a dictionary.

**Returns:**

  / *Type*: dict /

  Dictionary representation of this event.
      """
      return {
         'info': self.info,
         'state': self.state,
      }

   def to_json(self):
      """
Converts this ``ServiceEvent`` instance to a JSON string.

**Returns:**

  / *Type*: str /

  JSON string representation of this event.
      """
      return json.dumps(self.to_dict())

   @classmethod
   def from_dict(cls, data):
      """
Creates a ``ServiceEvent`` instance from a dictionary.

**Arguments:**

* ``data``

  / *Condition*: required / *Type*: dict /

  Dictionary containing event fields.

**Returns:**

  / *Type*: ServiceEvent /

  New instance populated from the dictionary.
      """
      info = data.get('info', {})
      return cls(
         service_name=info.get('name', ''),
         state=data.get('state', ''),
         info=info,
      )

   @classmethod
   def from_json(cls, json_str):
      """
Creates a ``ServiceEvent`` instance from a JSON string.

**Arguments:**

* ``json_str``

  / *Condition*: required / *Type*: str /

  JSON string containing event fields.

**Returns:**

  / *Type*: ServiceEvent /

  New instance populated from the JSON string.
      """
      return cls.from_dict(json.loads(json_str))
