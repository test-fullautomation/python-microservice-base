"""Service scaffold generator.

Generates complete project directories for new microservices based on
user selections (language, GUI type, infrastructure).  Used by the
Service Creator wizard in MicroserviceManagerGUI.

Supported combinations:

  Language   GUI type    Output
  --------   --------    ------
  Python     none        Async gRPC service (domain + adapter + proto)
  Python     html        Same + GUIs/service.html + service.js
  C++        none        CMake project (domain + adapter + proto + build scripts)
  C++        qml         Same + QML UI + preview app + stubs
  C++        wasm        Same + Qt Widgets WASM UI + build_wasm script
  C++        widget      Same + Qt Widgets desktop UI

All combinations optionally include:
  - Nomad job spec (.nomad.hcl)
  - Build/deploy scripts
  - README.md
"""

from .generator import generate_scaffold, ScaffoldSpec

__all__ = ["generate_scaffold", "ScaffoldSpec"]
