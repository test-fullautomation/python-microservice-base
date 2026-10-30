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
# *******************************************************************************
"""Where the GUI's files are, for the bridge serving them."""

import os

#: The GUI's own folder (the one holding ``web/`` and ``python/``). The
#: launcher sets it; without it the bridge runs from a checkout of the GUI
#: repo, two levels up from this package.
GUI_DIR_ENV = "DASGUI_GUI_DIR"


def gui_dir():
   """The GUI folder: ``$DASGUI_GUI_DIR``, else the repo this package sits in."""
   return os.environ.get(GUI_DIR_ENV) or os.path.abspath(
      os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
