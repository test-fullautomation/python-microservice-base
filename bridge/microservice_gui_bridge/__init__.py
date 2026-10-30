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
"""The Manager GUI's bridge: the FastAPI server between the GUI and the
services, with the hubs and test projects only the GUI uses.

It builds on MicroserviceBase (registry, gRPC reflection client, scaffold,
signals), which it depends on; services never need this package.
"""

from .paths import GUI_DIR_ENV, gui_dir

__version__ = "1.0.0"


def create_ui_bridge(bridge_type='fastapi', host='localhost', port=8000,
                     allowed_origins=None):
   """
A UIBridgePort implementation, not yet started.

``bridge_type`` is ``'fastapi'`` (the only one); ``allowed_origins`` is the
list of browser origins the bridge answers, ``None`` for
``MB_BRIDGE_ALLOWED_ORIGINS`` or the default for the bound address.
   """
   if bridge_type == 'fastapi':
      from .adapters.ui_bridge.fastapi_bridge import FastAPIBridge
      return FastAPIBridge(host=host, port=port, allowed_origins=allowed_origins)
   raise ValueError(f"Unknown UI bridge type: {bridge_type}")


__all__ = ["create_ui_bridge", "gui_dir", "GUI_DIR_ENV", "__version__"]
