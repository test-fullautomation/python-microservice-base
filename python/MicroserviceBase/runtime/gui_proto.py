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
``ServiceGui``: the contract a service uses to hand the Manager GUI its
own screen.

A service that ships a GUI folder serves two methods:

* ``GetGuiInfo``  -- the folder name and a checksum of its contents, so a
  client that already has that version downloads nothing.
* ``GetGuiFiles`` -- the folder as a ZIP, streamed in chunks (a Qt WASM
  build runs to several megabytes; one message would be a bad idea).

This extends ADR-019 (service-delivered GUI plugins) from the AMQP-era
``svc_api_get_gui_*`` calls to plain gRPC services discovered through
Consul.

Like ``adapters/signals/signal_proto.py``, the types are built from a
descriptor rather than generated ``*_pb2`` modules: no ``protoc`` step for
services, and no pin to the protobuf version that generated the code. Both
ends -- the service (``runtime/gui_server.py``) and the bridge -- use this
module, so they cannot drift apart.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

PACKAGE = "microservicebase.gui.v1"
SERVICE = "ServiceGui"

#: Fully-qualified name, for reflection and Consul metadata.
FULL_SERVICE_NAME = f"{PACKAGE}.{SERVICE}"

#: Chunk size of the ZIP stream. Below gRPC's 4 MiB default message limit
#: with room to spare, and large enough that a 20 MB package is ~80 messages.
CHUNK_BYTES = 256 * 1024

_F = descriptor_pb2.FieldDescriptorProto

#: message -> [(field, number, type[, label])]
_MESSAGES = {
    "GuiInfoRequest": [],
    "GuiInfo": [
        # The folder the files belong in, i.e. what Consul's Meta.gui says.
        ("folder", 1, _F.TYPE_STRING),
        # Stable hash of the folder's contents; the client's cache key.
        ("checksum", 2, _F.TYPE_STRING),
        ("size_bytes", 3, _F.TYPE_UINT64),
        ("file_count", 4, _F.TYPE_UINT32),
        # Empty when the service ships no GUI; the client then shows the
        # runtime card instead of waiting for files that never come.
        ("available", 5, _F.TYPE_BOOL),
    ],
    "GuiFilesRequest": [
        # What the client already has. Matching it ends the stream at once.
        ("known_checksum", 1, _F.TYPE_STRING),
    ],
    "GuiChunk": [
        ("data", 1, _F.TYPE_BYTES),
        # Repeated on every chunk so a client that joined late still knows
        # what it is assembling.
        ("checksum", 2, _F.TYPE_STRING),
        # True when the client's known_checksum was current: no data follows.
        ("unchanged", 3, _F.TYPE_BOOL),
    ],
}

#: service -> [(method, input, output, server_streaming)]
_SERVICES = {
    SERVICE: [
        ("GetGuiInfo", "GuiInfoRequest", "GuiInfo", False),
        ("GetGuiFiles", "GuiFilesRequest", "GuiChunk", True),
    ],
}


def _file_descriptor() -> descriptor_pb2.FileDescriptorProto:
    fd = descriptor_pb2.FileDescriptorProto(
        name="microservicebase/gui/v1/service_gui.proto", package=PACKAGE, syntax="proto3")
    for name, fields in _MESSAGES.items():
        msg = fd.message_type.add(name=name)
        for spec in fields:
            fname, number, ftype = spec[0], spec[1], spec[2]
            label = spec[3] if len(spec) > 3 else _F.LABEL_OPTIONAL
            f = msg.field.add(name=fname, number=number, type=ftype, label=label)
            parts = fname.split("_")
            f.json_name = parts[0] + "".join(p.title() for p in parts[1:])
    for sname, methods in _SERVICES.items():
        svc = fd.service.add(name=sname)
        for mname, inp, out, streaming in methods:
            svc.method.add(name=mname, input_type=f".{PACKAGE}.{inp}",
                           output_type=f".{PACKAGE}.{out}", server_streaming=streaming)
    return fd


# A pool of its own: a process may also load a generated module for the
# same names (a service that did run protoc, say).
_POOL = descriptor_pool.DescriptorPool()
_POOL.Add(_file_descriptor())


def message(name: str):
    """
The message class ``microservicebase.gui.v1.<name>``.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Short message name, e.g. ``"GuiInfo"``.

**Returns:**

* ``cls``

  / *Type*: type /

  A protobuf message class.
    """
    return message_factory.GetMessageClass(_POOL.FindMessageTypeByName(f"{PACKAGE}.{name}"))


def method_path(method: str) -> str:
    """``"/microservicebase.gui.v1.ServiceGui/<method>"``, the path a channel calls."""
    return f"/{FULL_SERVICE_NAME}/{method}"


def method_types(method: str):
    """``(request_cls, response_cls, server_streaming)`` of one method."""
    for mname, inp, out, streaming in _SERVICES[SERVICE]:
        if mname == method:
            return message(inp), message(out), streaming
    raise KeyError(method)
