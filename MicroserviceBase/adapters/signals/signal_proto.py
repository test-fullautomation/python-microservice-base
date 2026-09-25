#  Copyright 2020-2026 Robert Bosch GmbH
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
"""
Message classes and method paths of ``signal.proto`` (package ``signal``).

The signal services (``signal_graph``'s ``SignalQueryService`` and
``signal_discovery``'s ``SignalDiscoveryService``) serve no gRPC
reflection, so the bridge needs their types up front. They are built here
from a descriptor instead of generated ``*_pb2`` modules: no ``protoc``
step, and no pin to the protobuf version that generated the code.

Only the messages the bridge uses are declared; field numbers match
``signal.proto`` (graph-studio/reference/protos/signal.proto).
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

PACKAGE = "signal"
QUERY_SERVICE = "signal.SignalQueryService"
DISCOVERY_SERVICE = "signal.SignalDiscoveryService"

_F = descriptor_pb2.FieldDescriptorProto

#: message -> [(field, number, type, label, type_name)]
_MESSAGES = {
    "ServiceEndpoint": [("host", 1, _F.TYPE_STRING), ("port", 2, _F.TYPE_UINT32)],
    "GetSignalRequest": [("name", 1, _F.TYPE_STRING)],
    "SignalResponse": [("name", 1, _F.TYPE_STRING), ("value", 2, _F.TYPE_DOUBLE),
                       ("timestamp", 3, _F.TYPE_DOUBLE)],
    "SetSignalRequest": [("name", 1, _F.TYPE_STRING), ("value", 2, _F.TYPE_DOUBLE)],
    "SetSignalResponse": [("success", 1, _F.TYPE_BOOL), ("message", 2, _F.TYPE_STRING)],
    "ListSignalsRequest": [("prefix", 1, _F.TYPE_STRING)],
    "ListSignalsResponse": [("signals", 1, _F.TYPE_MESSAGE, _F.LABEL_REPEATED, ".signal.SignalMeta")],
    "SignalMeta": [("name", 1, _F.TYPE_STRING), ("kind", 2, _F.TYPE_STRING), ("unit", 3, _F.TYPE_STRING),
                   ("endpoint", 4, _F.TYPE_MESSAGE, _F.LABEL_OPTIONAL, ".signal.ServiceEndpoint")],
    "SubscribeRequest": [("signal_names", 1, _F.TYPE_STRING, _F.LABEL_REPEATED)],
    "SignalUpdate": [("signal_name", 1, _F.TYPE_STRING), ("value", 2, _F.TYPE_DOUBLE),
                     ("timestamp", 3, _F.TYPE_DOUBLE)],
}

#: service -> [(method, input, output, server_streaming)]
_SERVICES = {
    "SignalQueryService": [
        ("GetSignal", "GetSignalRequest", "SignalResponse", False),
        ("SetSignal", "SetSignalRequest", "SetSignalResponse", False),
        ("ListSignals", "ListSignalsRequest", "ListSignalsResponse", False),
        ("Subscribe", "SubscribeRequest", "SignalUpdate", True),
    ],
    "SignalDiscoveryService": [
        ("ListSignals", "ListSignalsRequest", "ListSignalsResponse", False),
    ],
}


def _file_descriptor() -> descriptor_pb2.FileDescriptorProto:
   fd = descriptor_pb2.FileDescriptorProto(name="mb_bridge/signal.proto", package=PACKAGE, syntax="proto3")
   for name, fields in _MESSAGES.items():
      msg = fd.message_type.add(name=name)
      for spec in fields:
         fname, number, ftype = spec[0], spec[1], spec[2]
         label = spec[3] if len(spec) > 3 else _F.LABEL_OPTIONAL
         f = msg.field.add(name=fname, number=number, type=ftype, label=label)
         if len(spec) > 4:
            f.type_name = spec[4]
         # proto3 JSON name, e.g. signal_names -> signalNames
         parts = fname.split("_")
         f.json_name = parts[0] + "".join(p.title() for p in parts[1:])
   for sname, methods in _SERVICES.items():
      svc = fd.service.add(name=sname)
      for mname, inp, out, streaming in methods:
         svc.method.add(name=mname, input_type=f".{PACKAGE}.{inp}", output_type=f".{PACKAGE}.{out}",
                        server_streaming=streaming)
   return fd


# A private pool: the process may also load a generated signal_pb2 (tests,
# the signals repo) into the default pool under the same names.
_POOL = descriptor_pool.DescriptorPool()
_POOL.Add(_file_descriptor())


def message(name: str):
   """
The message class ``signal.<name>``.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Short message name, e.g. ``"SubscribeRequest"``.

**Returns:**

* ``cls``

  / *Type*: type /

  A protobuf message class.
   """
   return message_factory.GetMessageClass(_POOL.FindMessageTypeByName(f"{PACKAGE}.{name}"))


def method_path(service: str, method: str) -> str:
   """``"/signal.<service>/<method>"``, the path gRPC channels call."""
   return f"/{PACKAGE}.{service}/{method}"


def method_types(service: str, method: str):
   """``(request_cls, response_cls, server_streaming)`` of one method."""
   for mname, inp, out, streaming in _SERVICES[service]:
      if mname == method:
         return message(inp), message(out), streaming
   raise KeyError(f"{service}/{method}")
