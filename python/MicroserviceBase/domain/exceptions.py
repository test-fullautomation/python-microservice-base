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
# File: exceptions.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Domain exception classes for service-related errors.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************


class ServiceError(Exception):
   """
Base exception for service-related errors.
   """
   pass


class TransportError(ServiceError):
   """
Raised when a transport-level operation fails.
   """
   pass


class ServiceNotFoundError(ServiceError):
   """
Raised when a requested service is not found in the registry.
   """
   pass


class MethodNotFoundError(ServiceError):
   """
Raised when a requested method is not found on a service.
   """
   pass
