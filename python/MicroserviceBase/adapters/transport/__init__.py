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
#   Transport sub-package initializer.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

# Lazy imports: the legacy RabbitMQ and EventBus transports are only needed
# by services that still opt into them.  The new gRPC/Consul runtime does not
# require `pika`, so don't let a missing optional dep break every import of
# MicroserviceBase.
try:
    from .rabbitmq_adapter import RabbitMQTransportAdapter  # noqa: F401
except ImportError:
    RabbitMQTransportAdapter = None  # type: ignore[assignment]

try:
    from .eventbus_adapter import EventBusTransportAdapter  # noqa: F401
except ImportError:
    EventBusTransportAdapter = None  # type: ignore[assignment]
