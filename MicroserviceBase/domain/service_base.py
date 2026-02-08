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
# File: service_base.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   Pure domain ServiceBase -- no pika imports, no infrastructure dependencies.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import re
import os
import base64
import hashlib
import inspect
import logging
import tempfile
import zipfile

from .models import ServiceInfo
from .messages import ResultType, ServiceRequest, ServiceResponse
from .exceptions import MethodNotFoundError

logger = logging.getLogger(__name__)


class ServiceBase:
   """
Pure domain base class for services.

All methods used to export APIs of a service must begin with the prefix 'svc_api_'.
This class handles API discovery, docstring parsing, and request dispatch.
Transport and registry interactions are delegated to injected ports.
   """

   _SERVICE_INFO = {
      'name': 'ServiceBase',
      'description': 'A template for services.',
      'shortdesc': '',
      'group': '',
      'tag': '',
      'version': '1.0.0',
      'routing_key': '',
      'gui_support': False,
      'methods': [],
      'methods_info': {},
   }

   _SERVICE_REQUEST_EXCHANGE = 'services_request'

   def __init__(self, transport=None, registry=None):
      """
Initialize the domain ServiceBase.

**Arguments:**

* ``transport``

  / *Condition*: optional / *Type*: TransportPort /

  A TransportPort implementation (optional, for pure domain use).

* ``registry``

  / *Condition*: optional / *Type*: ServiceRegistryPort /

  A ServiceRegistryPort implementation (optional, for pure domain use).
      """
      self._transport = transport
      self._registry = registry
      self.name = self._SERVICE_INFO['name']
      self._api_dict = self.get_svc_api_methods_dict()
      self._api_info_dict = self.get_svc_api_methods_info_dict(self._api_dict)
      # Internal methods: dispatchable via RPC but not published to clients
      _internal = {'svc_api_get_gui_files', 'svc_api_get_gui_checksum', 'svc_api_shutdown'}
      self._SERVICE_INFO['methods'] = [
         m for m in self._api_dict if m not in _internal
      ]
      self._SERVICE_INFO['methods_info'] = {
         k: v for k, v in self._api_info_dict.items() if k not in _internal
      }
      self._service_info = ServiceInfo.from_dict(self._SERVICE_INFO)

   def get_service_info(self):
      """
Return the ServiceInfo dataclass for this service.
      """
      return self._service_info

   def get_service_info_dict(self):
      """
Return the service info as a plain dict (backward compat).
      """
      return self._SERVICE_INFO

   def serve(self):
      """
Start serving requests via the transport port.
      """
      if self._transport is None:
         raise RuntimeError("No transport port configured. Cannot serve.")

      info = self._SERVICE_INFO
      print(f" [*] Service: {info['name']} v{info['version']}")
      if info.get('routing_key'):
         print(f" [*] Routing key: {info['routing_key']}")
      print(f" [*] API methods: {info['methods']}")
      print(f" [*] Starting service. Press CTRL+C to stop.")

      self._transport.consume(
         service_name=self.name,
         routing_key=self._SERVICE_INFO['routing_key'],
         exchange=self._SERVICE_REQUEST_EXCHANGE,
         handler=self.on_request,
      )

   def register_service(self):
      """
Register this service via the registry port.
      """
      if self._registry is not None:
         self._registry.register(self._SERVICE_INFO)

   def unregister_service(self):
      """
Unregister this service via the registry port.
      """
      if self._registry is not None:
         self._registry.unregister(self._SERVICE_INFO)

   def request_service(self, request_data, exchange_name, routing_key):
      """
Send an RPC request to another service via the transport port.

**Arguments:**

* ``request_data``

  / *Condition*: required / *Type*: dict /

  Dict with 'method' and 'args' keys (backward compat format).

* ``exchange_name``

  / *Condition*: required / *Type*: str /

  The exchange to publish to.

* ``routing_key``

  / *Condition*: required / *Type*: str /

  The routing key for the target service.

**Returns:**

  / *Type*: dict /

  The response dict from the target service.
      """
      if self._transport is None:
         raise RuntimeError("No transport port configured. Cannot make requests.")
      return self._transport.rpc_call(request_data, exchange_name, routing_key)

   def close(self):
      """
Close the service.
      """
      if self._transport is not None:
         self._transport.disconnect()

   def __del__(self):
      try:
         self.unregister_service()
      except Exception:
         logger.debug("Failed to unregister service during __del__", exc_info=True)

   @staticmethod
   def create_request_data(method_name, args):
      """
Create request data for a given method name and arguments.
      """
      request_data = {
         'method': method_name,
         'args': args,
      }
      return request_data

   def get_svc_api_methods_dict(self):
      """
Retrieve all service API methods (methods starting with 'svc_api_').
      """
      methods = {
         method: getattr(self, method)
         for method in dir(self)
         if method.startswith('svc_api') and callable(getattr(self, method))
      }
      if not self._SERVICE_INFO['gui_support']:
         methods.pop('svc_api_get_gui_files', None)
      return methods

   def get_svc_api_methods_info_dict(self, methods_dict):
      """
Retrieve information for all service APIs from their docstrings.
      """
      info_dict = {}
      for method_name, method in methods_dict.items():
         doc_string = method.__doc__
         if doc_string is None:
            logger.warning("API '%s' does not contain docstrings.", method_name)
            continue
         info_dict[method_name] = self.parse_docstring(doc_string)
      return info_dict

   def parse_docstring(self, docstring):
      """
Parse function's docstring to get arguments and return information.
      """
      result = {}

      arg_pattern = re.compile(
         r'\*\s+``([^`]*)``\s+/\s+\*Condition\*:(.*?)\s+/\s+\*Type\*:(.*?)\s+'
         r'(?:/\s+\*Default\*:(.*?))?\s*(?:/\s*([^*]+?.*?))?\n',
         re.DOTALL
      )
      return_pattern = re.compile(
         r'\*\*Returns:\*\*\s+/\s+\*Type\*:(.*?)(?=(?:/\s+\*\*\n|\Z))',
         re.DOTALL
      )

      try:
         arg_matches = arg_pattern.findall(docstring)
         arguments = []

         for match in arg_matches:
            arg_name, condition, arg_type, default_value, description = map(str.strip, match)
            description = re.sub(r'\n\s+\*\*.*', '', description)
            arguments.append({
               'name': arg_name,
               'condition': condition.strip() if condition else None,
               'type': arg_type.strip() if arg_type else None,
               'default': default_value.strip() if default_value else None,
               'description': description,
            })

         result['arguments'] = arguments

         return_matches = return_pattern.findall(docstring)
         if return_matches:
            result['return_type'] = return_matches[0].strip()
      except (re.error, ValueError, IndexError) as ex:
         logger.warning("Unable to analyse the docstring: '%s'. Please check the docstring format.", docstring, exc_info=True)

      return result

   def svc_api_get_version(self):
      """
Get the service version.

**Returns:**

  / *Type*: str /

  Version of the service.
      """
      return self._SERVICE_INFO['version']

   def svc_api_get_gui_files(self):
      """
Compress and return GUI files as bytes.
      """
      file_content = None
      if self._SERVICE_INFO['gui_support']:
         service_file = inspect.getfile(type(self))
         service_dir = os.path.dirname(os.path.abspath(service_file))
         guis_path = os.path.join(service_dir, 'GUIs')

         if not os.path.isdir(guis_path):
            logger.warning("GUIs directory not found at %s", guis_path)
            return file_content

         zip_fd, zip_file_path = tempfile.mkstemp(suffix='.zip')
         os.close(zip_fd)
         try:
            with zipfile.ZipFile(zip_file_path, 'w') as zipf:
               for root, dirs, files in os.walk(guis_path):
                  for file in files:
                     full_path = os.path.join(root, file)
                     arcname = os.path.relpath(full_path, guis_path)
                     zipf.write(full_path, arcname)

            with open(zip_file_path, 'rb') as file:
               file_content = file.read()
         finally:
            if os.path.exists(zip_file_path):
               os.remove(zip_file_path)

      return file_content

   def svc_api_get_gui_checksum(self):
      """
Get an MD5 checksum of all GUI files.

Returns None when gui_support is disabled or the GUIs directory is missing.

**Returns:**

  / *Type*: str /

  MD5 hex-digest of the GUI files, or None.
      """
      if not self._SERVICE_INFO['gui_support']:
         return None

      service_file = inspect.getfile(type(self))
      service_dir = os.path.dirname(os.path.abspath(service_file))
      guis_path = os.path.join(service_dir, 'GUIs')

      if not os.path.isdir(guis_path):
         return None

      hasher = hashlib.md5()
      for root, dirs, files in os.walk(guis_path):
         dirs.sort()
         for file in sorted(files):
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, guis_path).replace('\\', '/')
            hasher.update(rel_path.encode('utf-8'))
            with open(full_path, 'rb') as f:
               while True:
                  chunk = f.read(8192)
                  if not chunk:
                     break
                  hasher.update(chunk)

      return hasher.hexdigest()

   def svc_api_shutdown(self):
      """
Gracefully shut down this service.
      """
      logger.info("svc_api_shutdown called — unregistering and stopping")
      try:
         self.unregister_service()
      except Exception as ex:
         logger.warning("unregister_service() during shutdown: %s", ex)
      if self._transport is not None:
         self._transport.stop_consuming()
      return {"status": "shutting_down"}

   def is_specific_request(self, request):
      """
Check if the request is a specific request. Override in subclasses.
      """
      return False

   def on_specific_request(self, request, body):
      """
Handle a specific request. Override in subclasses.

**Arguments:**

* ``request``

  / *Condition*: required / *Type*: str /

  The request method name.

* ``body``

  / *Condition*: required / *Type*: dict /

  The parsed request body dict.

**Returns:**

  / *Type*: ServiceResponse /

  A ServiceResponse, or None if not handled.
      """
      raise Exception("Not supported request")

   def dispatch_request(self, request_body):
      """
Dispatch a parsed request body and return a ServiceResponse.

This is the core domain logic: given a request dict with 'method' and 'args',
find the matching API method, call it, and return a structured response.

**Arguments:**

* ``request_body``

  / *Condition*: required / *Type*: dict /

  Dict with 'method' and 'args' keys.

**Returns:**

  / *Type*: ServiceResponse /

  ServiceResponse with result type and data.
      """
      response_data = "Non-supported request"
      result_type = ResultType.FAIL
      request_api = ""

      try:
         request_api = request_body['method']
         if request_body['method'] in self._api_dict:
            args = request_body['args']
            if not args:
               response_data = self._api_dict[request_body['method']]()
            elif isinstance(args, str):
               response_data = self._api_dict[request_body['method']](args)
            else:
               response_data = self._api_dict[request_body['method']](*args)
            result_type = ResultType.PASS
      except Exception as ex:
         result_type = ResultType.EXCEPT
         response_data = str(ex)

      if response_data == "Non-supported request" and self.is_specific_request(request_api):
         return None  # Signal that transport should call on_specific_request

      if isinstance(response_data, bytes):
         response_data = base64.b64encode(response_data).decode('utf-8')

      return ServiceResponse(
         request=request_api,
         result=result_type.value,
         result_data=response_data,
      )

   def on_request(self, ch, method, props, body):
      """
Handle an incoming request (transport callback signature).

This method is called by the transport adapter. It delegates to
dispatch_request for the actual domain logic, then uses the transport
to send the response back.

**Arguments:**

* ``ch``

  / *Condition*: required / *Type*: object /

  Channel object from transport.

* ``method``

  / *Condition*: required / *Type*: object /

  Delivery method from transport.

* ``props``

  / *Condition*: required / *Type*: object /

  Message properties from transport.

* ``body``

  / *Condition*: required / *Type*: bytes /

  Raw message body (bytes or dict).
      """
      import json

      if isinstance(body, bytes):
         body = json.loads(body.decode('utf-8'))

      response = self.dispatch_request(body)

      if response is None:
         # Specific request -- delegate to subclass handler
         self.on_specific_request(body['method'], body)
         return

      ch.basic_publish(
         exchange='',
         routing_key=props.reply_to,
         properties=type(props)(correlation_id=props.correlation_id),
         body=response.get_json(),
      )
      ch.basic_ack(delivery_tag=method.delivery_tag)
