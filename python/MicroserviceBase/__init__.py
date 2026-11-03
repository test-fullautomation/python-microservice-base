#  Copyright 2020-2025 Robert Bosch GmbH
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
#
# File: __init__.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   MicroserviceBase package init module.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

# Domain layer -- pure business logic, zero external dependencies
from .domain.models import ServiceInfo, ServiceMethod, MethodArgument
from .domain.messages import ResultType, ServiceRequest, ServiceResponse, ServiceEvent
from .domain.exceptions import (
    ServiceError,
    TransportError,
    ServiceNotFoundError,
    MethodNotFoundError,
)

# Port interfaces -- abstract contracts the domain depends on
from .ports.transport import TransportPort
from .ports.registry import ServiceRegistryPort
from .ports.ui_bridge import UIBridgePort

# Domain services
from .domain.service_base import ServiceBase
from .domain.service_registry import ServiceRegistry

# Factory -- composition root for wiring ports to adapters
from .factory import create_transport, create_registry, create_ui_bridge
