#  Copyright 2020-2024 Robert Bosch GmbH
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
# File: ServiceBase.py
#
# Initially created by Nguyen Huynh Tri Cuong (RBVH/ECM51) / Nov 2023
#
# Description:
#   Provide the base class for services in the system's infrastructure.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong (RBVH/ECM51)
# - Initialize
#
# *******************************************************************************
import abc
import pika
import json
import collections
import zipfile
import os
import base64
import uuid
import re
import sys
import argparse


class ResultType:
   """
Result Types.
   """
   PASS = "pass"
   FAIL = "fail"
   EXCEPT = "exception"

   def __init__(self):
      pass


class ResponseMessage(object):
   """
Response message class
   """
   def __init__(self, request="", result=ResultType.PASS, result_data=""):
      """
Constructor for the ResponseMessage class.

**Arguments:**

* ``request``

  / *Condition*: optional / *Type*: str / *Default*: "" /

  The request string.

* ``result``

  / *Condition*: optional / *Type*: ResultType / *Default*: ResultType.PASS /

  The result of processing the request.

* ``result_data``

  / *Condition*: optional / *Type*: str / *Default*: "" /

  The result data returned.

**Returns:**

(*no returns*)
      """
      self.request = request
      self.result = result
      self.result_data = result_data

   def get_json(self):
      """
Convert the response message to JSON format.

**Returns:**

  / *Type*: str /

  The response message in JSON format.
      """
      return json.dumps(collections.OrderedDict(sorted(self.__dict__.items())))

   def get_data(self):
      """
Retrieve the result data as a string.

**Returns:**

  / *Type*: str /

  The result data as a string.
      """
      return self.result_data


class ServiceBase:
   _SERVICE_INFO = {
      'name': 'ServiceBase',
      'description': 'A template for services.',
      'shortdesc': '',
      'group': '',
      'tag': '',
      'version': '1.0.0',
      'routing_key': '',
      'gui_support': False,
      # Other details
      'methods': [],
      'methods_info': {}
   }

   _SERVICE_REQUEST_EXCHANGE = 'services_request'

   def __init__(self, cmd_args=None):
      """
Base class for services in the system's infrastructure.

This class provides the foundational structure and common functionalities 
that all service classes must inherit to integrate with the system's infrastructure.
Users should extend this class to implement custom service logic, ensuring consistent 
behavior and interaction with the overall system.

All methods used to export APIs of a service must begin with the prefix 'svc_api_'.
      """
      self.connection = None      
      self.name = self._SERVICE_INFO['name']
      self._kw_args = self.parse_arguments(cmd_args)
      self._spec_args = self.parse_spec_arguments(cmd_args)
      self._api_dict = self.get_svc_api_methods_dict()
      self._api_info_dict = self.get_svc_api_methods_info_dict(self._api_dict)
      self._SERVICE_INFO['methods'] = list(self._api_dict.keys())
      self._SERVICE_INFO['methods_info'] = self._api_info_dict
      self.connect_broker(**self._kw_args)
      self.register_service()

   def parse_arguments(self, cmd_args):
      """
Parse basic service arguments from the command line.

**Arguments:**

* ``cmd_args``

  / *Condition*: required / *Type*: list /

  Command-line arguments to be parsed.

**Returns:**

  / *Type*: dict /

  A dictionary containing the parsed arguments.
      """
      parser = argparse.ArgumentParser(description=f'Start the {self.name} service.')
      parser.add_argument('--host', type=str, help=f'The rabbitMQ host for the {self.name} service')
      parser.add_argument('--port', type=int, help=f'The port for the {self.name} service')
      parser.add_argument('--virtual_host', type=str, help=f'The virtual host for the {self.name} service')
      parser.add_argument('--username', type=str, help='The username for the RabbitMQ service')
      parser.add_argument('--password', type=str, help='The password for the RabbitMQ service')
      
      if cmd_args is not None:
         args, remaining_args = parser.parse_known_args(cmd_args)
      else:
         args, remaining_args = parser.parse_known_args()

      
      host = args.host or os.getenv('RABBITMQ_HOST') or 'localhost'
      port = args.port or int(os.getenv('RABBITMQ_PORT', 5672))
      virtual_host = args.virtual_host or os.getenv('RABBITMQ_VIRTUAL_HOST') or '/'
      username = args.username or os.getenv('RABBITMQ_USERNAME') or 'guest'
      password = args.password or os.getenv('RABBITMQ_PASSWORD') or 'guest'
      
      return {
          'host': host,
          'port': port,
          'virtual_host': virtual_host,
          'credentials': pika.PlainCredentials(username, password)
      }

   def parse_spec_arguments(self, cmd_args):
      """
Parse specific arguments for each customized service.

This method should be overridden by subclasses to handle service-specific arguments.

**Arguments:**

* ``cmd_args``

  / *Condition*: required / *Type*: list /

  Command-line arguments to be parsed.

**Returns:**

  / *Type*: dict /

  A dictionary containing the parsed specific arguments.
      """
      # This method is meant to be overridden by derived classes
      return {}

   def close(self):
      """
Close the service connection.

**Returns:**

(*no returns*)
      """
      self.connection.close()

   def __del__(self):
      """
Destructor for the ServiceBase class.

This method is called when an instance of the ServiceBase class is about to be destroyed.
It ensures that any necessary cleanup is performed and service connections are properly closed.

**Returns:**

(*no returns*)
      """
      self.unregister_service()
      self.close()

   @staticmethod
   def create_request_data(method_name, args):
      """
Create request data for a given method name and arguments.

**Arguments:**

* ``method_name``

  / *Condition*: required / *Type*: str /

  The name of the method for which the request is being created.

* ``args``

  / *Condition*: required / *Type*: list /

  The list of arguments for the method.

**Returns:**

  / *Type*: dict /

  A dictionary containing the method name and arguments.
      """
      request_data = {
            'method': request_api,
            'args': args_list
      }
      return  request_data

   def connect_broker(self, **kwargs):
      """
Establish a connection to the broker.

**Arguments:**

* ``**kwargs``

  / *Condition*: optional / *Type*: dict /

  Additional keyword arguments for broker connection parameters.

**Returns:**

(*no returns*)
      """
      try:
         self.connection = pika.BlockingConnection(pika.ConnectionParameters(**kwargs))
      except Exception as ex:
         print(" [x] Unable to connect broker. Reason:" + str(ex))

   def serve(self):
      """
Call to start service serving.

**Returns:**

(*no returns*)
      """
      channel = self.connection.channel()

      channel.exchange_declare(exchange=ServiceBase._SERVICE_REQUEST_EXCHANGE, exchange_type='direct')
      channel.queue_declare(queue=self.name)

      # Purge the queue
      channel.queue_purge(queue=self.name)
      print(f"Queue '{self.name}' purged")

      # Bind the queue to the exchange with a routing key
      channel.queue_bind(exchange=ServiceBase._SERVICE_REQUEST_EXCHANGE, queue=self.name, routing_key=self._SERVICE_INFO['routing_key'])

      channel.basic_qos(prefetch_count=1)
      channel.basic_consume(queue=self.name, on_message_callback=self.on_request)

      print(" [x] Awaiting RPC requests")
      channel.start_consuming()

   def register_service(self):
      """
Register a service to the ServiceRegistry.

**Returns:**

(*no returns*)
      """
      exchange_name = 'service_information'
      channel = self.connection.channel()
      channel.exchange_declare(exchange=exchange_name, exchange_type='topic')

      service_info = {
         'info': self._SERVICE_INFO,
         'state': 'on'
      }

      # Ensure the queue is durable and named to be reused
      queue_name = 'service_infor_queue'
      channel.queue_declare(queue=queue_name, durable=True)

      # Bind the queue to specific routing keys
      channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key='service.information')

      channel.basic_publish(
         exchange=exchange_name,
         routing_key='service.information',
         body=json.dumps(service_info),
         properties=pika.BasicProperties(
            delivery_mode=2,  # Make message persistent
         )
      )

      print(" [x] Registered service to Registry Service")

   def unregister_service(self):
      """
Unregister a service from the ServiceRegistry.

**Returns:**

(*no returns*)
      """
      exchange_name = 'service_information'
      channel = self.connection.channel()
      channel.exchange_declare(exchange=exchange_name, exchange_type='topic')

      service_info = {
         'info': self._SERVICE_INFO,
         'state': 'off'
      }

      # Ensure the queue is durable and named to be reused
      queue_name = 'service_infor_queue'
      channel.queue_declare(queue=queue_name, durable=True)

      # Bind the queue to specific routing keys
      channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key='service.information')

      channel.basic_publish(
         exchange=exchange_name,
         routing_key='service.information',
         body=json.dumps(service_info),
         properties=pika.BasicProperties(
            delivery_mode=2,  # Make message persistent
         )
      )

      print(" [x] Unregistered service from Registry Service")

   def request_service(self, request_data, exchange_name, routing_key):
      """
Send a service request to a specific exchange with a given routing key.

**Arguments:**

* ``request_data``

  / *Condition*: required / *Type*: dict /

  The data for the service request.

* ``exchange_name``

  / *Condition*: required / *Type*: str /

  The name of the exchange to send the request to.

* ``routing_key``

  / *Condition*: required / *Type*: str /

  The routing key for the request.

**Returns:**

(*no returns*)
      """
      connection = pika.BlockingConnection(pika.ConnectionParameters(**self._kw_args))
      channel = connection.channel()
      result = channel.queue_declare(queue='', exclusive=True)
      callback_queue = result.method.queue
      correlation_id = str(uuid.uuid4())
      resp = None
      def on_response(ch, method, properties, body):
         if properties.correlation_id == correlation_id:
            response = json.loads(body.decode())
            print(f" [.] Got response: {response}")
            nonlocal resp
            resp = response
            ch.stop_consuming()

      channel.basic_consume(queue=callback_queue, on_message_callback=on_response, auto_ack=True)
      print(f" [x] Requesting Service with data: {request_data}")
      channel.basic_publish(
         exchange=exchange_name,
         routing_key=routing_key,
         properties=pika.BasicProperties(
            reply_to=callback_queue,
            correlation_id=correlation_id,
         ),
         body=json.dumps(request_data),
      )

      channel.start_consuming()
      # while resp is None:
      #    connection.process_data_events()
      connection.close()
      return resp

   def get_svc_api_methods_dict(self):
      """
Retrieve all service API methods provided by the service (methods starting with the prefix 'svc_api_').

**Returns:**

  / *Type*: dict /

  A dictionary containing the names and references of all service API methods.
      """
      methods = {method: getattr(self, method) for method in dir(self) if method.startswith('svc_api') and callable(getattr(self, method))}
      if not self._SERVICE_INFO['gui_support']:
         del methods['svc_api_get_gui_files']
      return methods
   
   def get_svc_api_methods_info_dict(self, methods_dict):
      """
Retrieve information for all service APIs from the docstrings of the methods.

**Arguments:**

* ``methods_dict``

  / *Condition*: required / *Type*: dict /

  A dictionary containing the names and references of all service API methods.

**Returns:**

  / *Type*: dict /

  A dictionary containing the information of all service APIs extracted from their docstrings.
      """
      info_dict = {}
      for method_name, method in methods_dict.items():
         doc_string = method.__doc__
         if doc_string is None:
            print(f" [!] API '{method_name}' does not contain docstrings.")
            continue
         info_dict[method_name] = self.parse_docstring(method.__doc__)
      return info_dict

   def parse_docstring(self, docstring):
      """
Parse function's docstring to get arguments and return information.

**Arguments:**

* ``docstring``

  / *Condition*: required / *Type*: str /

  Function's docstring.

**Returns:**

  / *Type*: str /

  Payloads of the waiting signal if received.
      """
      result = {}

      arg_pattern = re.compile(r'\*\s+``([^`]*)``\s+/\s+\*Condition\*:(.*?)\s+/\s+\*Type\*:(.*?)\s+(?:/\s+\*Default\*:(.*?))?\s*(?:/\s*([^*]+?.*?))?\n', re.DOTALL)
      return_pattern = re.compile(r'\*\*Returns:\*\*\s+/\s+\*Type\*:(.*?)(?=(?:/\s+\*\*\n|\Z))', re.DOTALL)

      try:
         # Find matches for arguments
         arg_matches = arg_pattern.findall(docstring)
         arguments = []

         for match in arg_matches:
            arg_name, condition, arg_type, default_value, description = map(str.strip, match)
            # Fix the description to exclude the next argument's type information
            description = re.sub(r'\n\s+\*\*.*', '', description)
            arguments.append({
               'name': arg_name,
               'condition': condition.strip() if condition else None,
               'type': arg_type.strip() if arg_type else None,
               'default': default_value.strip() if default_value else None,
               'description': description
            })

         result['arguments'] = arguments

         # Find matches for return type
         return_matches = return_pattern.findall(docstring)
         if return_matches:
            result['return_type'] = return_matches[0].strip()
      except Exception as ex:
         print(f" [!] Unable to analysis the docstring: '{docstring}'. Please check the docstring format.")

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
      # Compress the files into a ZIP file
      file_content = None
      if self._SERVICE_INFO['gui_support']:
         zip_file_path = 'files.zip'
         with zipfile.ZipFile(zip_file_path, 'w') as zipf:
            for root, dirs, files in os.walk('GUIs'):
               for file in files:
                  zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), 'GUIs'))

         with open(zip_file_path, 'rb') as file:
            file_content = file.read()

         os.remove(zip_file_path)

      return file_content

   def is_specific_request(self, request):
      """
Check if the request is a specific request.

**Arguments:**

* ``request``

  / *Condition*: required / *Type*: object /

  The request object to be checked.

**Returns:**

  / *Type*: bool /

  True if the request is a specific request, otherwise False.
      """
      return False

   def on_specific_request(self, ch, method, props, body):
      """
Handle the event when a specific request is received.

**Arguments:**

* ``ch``

  / *Condition*: required / *Type*: pika.channel.Channel /

  The channel object from the pika library.

* ``method``

  / *Condition*: required / *Type*: pika.spec.Basic.Deliver /

  The method object containing delivery information from the pika library.

* ``props``

  / *Condition*: required / *Type*: pika.spec.BasicProperties /

  The properties of the message from the pika library.

* ``body``

  / *Condition*: required / *Type*: dict /

  The body of the message as a dictionary.

**Returns:**

(*no returns*)
      """
      raise Exception("Not suppoted request")

   def on_request(self, ch, method, props, body):
      """
Handle an incoming request.

**Arguments:**

* ``ch``

  / *Condition*: required / *Type*: pika.channel.Channel /

  The channel object from the pika library.

* ``method``

  / *Condition*: required / *Type*: pika.spec.Basic.Deliver /

  The method object containing delivery information from the pika library.

* ``props``

  / *Condition*: required / *Type*: pika.spec.BasicProperties /

  The properties of the message from the pika library.

* ``body``

  / *Condition*: required / *Type*: bytes /

  The body of the message as bytes.

**Returns:**

(*no returns*)
      """
      response = "Non-supported request"
      result_type = ResultType.FAIL
      request_api = ""
      try:
         if isinstance(body, bytes):
            body = json.loads(body.decode('utf-8'))

         request_api = body['method']
         if body['method'] in self._api_dict:
            if not body['args']:
               response = self._api_dict[body['method']]()
            elif isinstance(body['args'], str):
               response = self._api_dict[body['method']](body['args'])
            else:
               response = self._api_dict[body['method']](*body['args'])
            result_type = ResultType.PASS
      except Exception as ex:
         result_type = ResultType.EXCEPT
         response = str(ex)

      if response == "Non-supported request" and self.is_specific_request(request_api):
         self.on_specific_request(ch, method, props, body)
      else:
         if isinstance(response, bytes):
            # Convert bytes data to base64 encoded string
            response = base64.b64encode(response).decode('utf-8')

         resp = ResponseMessage(request_api, result_type, response)
         # print(props.reply_to)
         ch.basic_publish(exchange='',
                        routing_key=props.reply_to,
                        properties=pika.BasicProperties(correlation_id=props.correlation_id),
                        body=resp.get_json())
         ch.basic_ack(delivery_tag=method.delivery_tag)


if __name__ == '__main__':
   svc = ServiceBase(sys.argv[1:])
   svc.serve()
