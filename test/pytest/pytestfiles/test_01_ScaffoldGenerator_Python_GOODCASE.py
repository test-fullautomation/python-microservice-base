# **************************************************************************************************************
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
# --------------------------------------------------------------------------------------------------------------
#
# test_01_ScaffoldGenerator_Python_GOODCASE.py
#
# Nguyen Huynh Tri Cuong (MS/EMC51)
#
# 10.05.2026 - 15:35:51
#
# --------------------------------------------------------------------------------------------------------------

import pytest
from pytestlibs.CExecute import CExecute

# --------------------------------------------------------------------------------------------------------------

class Test_ScaffoldGenerator_Python_GOODCASE:

# --------------------------------------------------------------------------------------------------------------
   # (L1 static check)
   # Expected: All expected files written; key markers present in main.py / .proto / nomad.hcl
   @pytest.mark.parametrize(
      "Description", ["Generate a Python single-service project and assert file layout",]
   )
   def test_MSB_0001(self, Description):
      nReturn = CExecute.Execute("MSB_0001")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L2 syntactic check)
   # Expected: Every .py compiles; protoc generates calculator_pb2.py + calculator_pb2_grpc.py
   @pytest.mark.parametrize(
      "Description", ["Generated Python project compiles (py_compile + protoc)",]
   )
   def test_MSB_0002(self, Description):
      nReturn = CExecute.Execute("MSB_0002")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L3 build check)
   # Expected: scripts/generate_protos.py exits 0 and writes proto/*_pb2*.py
   @pytest.mark.parametrize(
      "Description", ["Generated Python project's scripts/generate_protos.py runs cleanly",]
   )
   def test_MSB_0003(self, Description):
      nReturn = CExecute.Execute("MSB_0003")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L4 runtime check (uses real Consul agent in -dev mode))
   # (Requires consul on PATH; SKIPPED otherwise)
   # Expected: calculator_service appears in Consul catalog (passing); reflection lists Calculator.Add
   @pytest.mark.parametrize(
      "Description", ["Generated Python service registers in Consul and answers a gRPC call",]
   )
   def test_MSB_0004(self, Description):
      nReturn = CExecute.Execute("MSB_0004")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L1 static check, monorepo layout)
   # Expected: Per-service src tree + shared toolbox.proto + per-service deploy artefacts emitted
   @pytest.mark.parametrize(
      "Description", ["Generate a Python monorepo project (Toolbox = Calculator + Echo) and assert layout",]
   )
   def test_MSB_0006(self, Description):
      nReturn = CExecute.Execute("MSB_0006")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L2 syntactic check, monorepo layout)
   # Expected: py_compile clean; protoc emits toolbox_pb2.py + toolbox_pb2_grpc.py
   @pytest.mark.parametrize(
      "Description", ["Python monorepo compiles + shared .proto compiles",]
   )
   def test_MSB_0007(self, Description):
      nReturn = CExecute.Execute("MSB_0007")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L3 build check, monorepo layout)
   # Expected: exit 0; toolbox_pb2.py + toolbox_pb2_grpc.py written under proto/
   @pytest.mark.parametrize(
      "Description", ["Python monorepo's scripts/generate_protos.py runs cleanly",]
   )
   def test_MSB_0010(self, Description):
      nReturn = CExecute.Execute("MSB_0010")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L4 runtime check, monorepo layout)
   # (Requires consul on PATH; SKIPPED otherwise)
   # Expected: Service appears in Consul (passing); reflection lists calculator.v1.CalculatorService
   @pytest.mark.parametrize(
      "Description", ["Python monorepo Calculator service registers in Consul + reflection works",]
   )
   def test_MSB_0011(self, Description):
      nReturn = CExecute.Execute("MSB_0011")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
