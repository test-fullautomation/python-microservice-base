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
# test_02_ScaffoldGenerator_Cpp_GOODCASE.py
#
# Nguyen Huynh Tri Cuong (MS/EMC51)
#
# 10.05.2026 - 15:35:51
#
# --------------------------------------------------------------------------------------------------------------

import pytest
from pytestlibs.CExecute import CExecute

# --------------------------------------------------------------------------------------------------------------

class Test_ScaffoldGenerator_Cpp_GOODCASE:

# --------------------------------------------------------------------------------------------------------------
   # (L1 static check, multi_proto layout)
   # Expected: Per-service .proto + domain + adapter present; CMakeLists / main.cpp / nomad.hcl emitted
   @pytest.mark.parametrize(
      "Description", ["Generate a C++ multi_proto project (Toolbox=Calculator+Echo) and assert layout",]
   )
   def test_MSB_0005(self, Description):
      nReturn = CExecute.Execute("MSB_0005")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L1 static check, single-service C++)
   # Expected: CMakeLists, main.cpp, EchoService domain + adapter, echo.proto + .nomad.hcl emitted
   @pytest.mark.parametrize(
      "Description", ["Generate a C++ single-service project (Echo) and assert layout",]
   )
   def test_MSB_0008(self, Description):
      nReturn = CExecute.Execute("MSB_0008")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L2 syntactic check, single-service C++)
   # Expected: echo.proto compiles to a FileDescriptorSet without errors
   @pytest.mark.parametrize(
      "Description", ["C++ single-service .proto parses cleanly through protoc",]
   )
   def test_MSB_0012(self, Description):
      nReturn = CExecute.Execute("MSB_0012")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L2 syntactic check, multi_proto layout)
   # Expected: calculator.proto and echo.proto each compile independently
   @pytest.mark.parametrize(
      "Description", ["C++ multi_proto: every per-service .proto parses cleanly",]
   )
   def test_MSB_0013(self, Description):
      nReturn = CExecute.Execute("MSB_0013")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L1 static check, C++ monorepo)
   # Expected: Per-service src tree + shared toolbox.proto + per-service deploy artefacts emitted
   @pytest.mark.parametrize(
      "Description", ["Generate a C++ monorepo project (Toolbox = Calculator + Echo) and assert layout",]
   )
   def test_MSB_0014(self, Description):
      nReturn = CExecute.Execute("MSB_0014")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L2 syntactic check, C++ monorepo)
   # Expected: Single shared .proto declaring multiple services compiles
   @pytest.mark.parametrize(
      "Description", ["C++ monorepo shared toolbox.proto parses cleanly",]
   )
   def test_MSB_0015(self, Description):
      nReturn = CExecute.Execute("MSB_0015")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
   # (L3 build check, C++ single-service)
   # (Skips when cmake or system gRPC is unavailable)
   # Expected: cmake -S . -B build_test exits 0 (or skips when cmake/gRPC absent)
   @pytest.mark.parametrize(
      "Description", ["C++ single-service CMake configure step succeeds",]
   )
   def test_MSB_0016(self, Description):
      nReturn = CExecute.Execute("MSB_0016")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
