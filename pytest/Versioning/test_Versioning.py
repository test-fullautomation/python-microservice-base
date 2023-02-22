#  Copyright 2020-2022 Robert Bosch GmbH
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
# test_Versioning.py
#
# XC-CI1/ECA3-Queckenstedt
#
# 22.02.2023
#
#                                     !!! initial sample only !!!
#
# --------------------------------------------------------------------------------------------------------------

# -- import standard Python modules
import os, sys, time, pytest

# -- import own Python modules (containing the code to be tested)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))) # to make sure to hit the package relative to this file at first

# --------------------------------------------------------------------------------------------------------------

class Test_Versioning:
    """Basic versioning test"""

    @pytest.mark.parametrize(
        "Description", ["Basic versioning test",]
    )
    def test_versioning(self, Description):
        """pytest versioning"""
        try:
            from MicroserviceBase.version import VERSION
            from MicroserviceBase.version import VERSION_DATE
        except Exception as reason:
            print(str(reason))
            assert False

# eof class Test_Versioning:

# --------------------------------------------------------------------------------------------------------------
