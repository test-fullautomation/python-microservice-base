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
# test_03_ScaffoldGenerator_Cpp_BADCASE.py
#
# Nguyen Huynh Tri Cuong (MS/EMC51)
#
# 10.05.2026 - 15:35:51
#
# --------------------------------------------------------------------------------------------------------------

import pytest
from pytestlibs.CExecute import CExecute

# --------------------------------------------------------------------------------------------------------------

class Test_ScaffoldGenerator_Cpp_BADCASE:

# --------------------------------------------------------------------------------------------------------------
   # (Documents that multi_proto is C++-only in this release)
   # Expected: generate_scaffold raises NotImplementedError mentioning python multi_proto
   @pytest.mark.parametrize(
      "Description", ["Python + multi_proto layout must raise NotImplementedError",]
   )
   def test_MSB_0009(self, Description):
      nReturn = CExecute.Execute("MSB_0009")
      assert nReturn == 0
# --------------------------------------------------------------------------------------------------------------
