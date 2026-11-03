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
"""The Python runtime's ServiceGui matches protos/.../service_gui.proto.

runtime/gui_proto.py builds its descriptor in code; this compiles the
.proto with grpc_tools and compares the two: package, every message's
fields (name, number, type, label) and every method (types, streaming)."""

import os
import tempfile

import pytest

from MicroserviceBase.runtime import gui_proto

protoc = pytest.importorskip("grpc_tools.protoc")
from google.protobuf import descriptor_pb2  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROTOS = os.path.join(REPO, "protos")
PROTO = "microservicebase/gui/v1/service_gui.proto"


def _compiled():
   with tempfile.TemporaryDirectory() as tmp:
      out = os.path.join(tmp, "set.pb")
      rc = protoc.main(["protoc", f"-I{PROTOS}", f"--descriptor_set_out={out}", PROTO])
      assert rc == 0, f"protoc failed on {PROTO}"
      fds = descriptor_pb2.FileDescriptorSet()
      with open(out, "rb") as fh:
         fds.ParseFromString(fh.read())
   (fd,) = fds.file
   return fd


def _messages(fd):
   return {m.name: [(f.name, f.number, f.type, f.label, f.type_name) for f in m.field]
           for m in fd.message_type}


def _methods(fd):
   return {(s.name, m.name): (m.input_type, m.output_type, m.client_streaming, m.server_streaming)
           for s in fd.service for m in s.method}


class Test_ServiceGuiContract:

   def test_same_file_and_package(self):
      ref, ours = _compiled(), gui_proto._file_descriptor()
      assert ours.name == ref.name == PROTO
      assert ours.package == ref.package == gui_proto.PACKAGE
      assert ours.syntax == ref.syntax == "proto3"

   def test_same_messages(self):
      assert _messages(gui_proto._file_descriptor()) == _messages(_compiled())

   def test_same_methods(self):
      assert _methods(gui_proto._file_descriptor()) == _methods(_compiled())

   def test_method_paths(self):
      ref = _compiled()
      paths = {f"/{ref.package}.{s.name}/{m.name}" for s in ref.service for m in s.method}
      assert paths == {gui_proto.method_path("GetGuiInfo"), gui_proto.method_path("GetGuiFiles")}
