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
# File: rabbitmq_config.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Nov 2023.
#
# Description:
#
#   RabbitMQ connection configuration dataclass.
#
# History:
#
# 24.11.2023 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import os
import argparse
from dataclasses import dataclass


@dataclass
class RabbitMQConfig:
   """
Configuration for connecting to RabbitMQ.
   """
   host: str = 'localhost'
   port: int = 5672
   virtual_host: str = '/'
   username: str = 'guest'
   password: str = 'guest'

   def to_connection_params(self):
      """
Convert to pika ConnectionParameters kwargs.

**Returns:**

  dict suitable for pika.ConnectionParameters(**kwargs).
      """
      import pika
      return {
         'host': self.host,
         'port': self.port,
         'virtual_host': self.virtual_host,
         'credentials': pika.PlainCredentials(self.username, self.password),
      }

   @classmethod
   def from_cmd_args(cls, cmd_args=None, service_name='Service'):
      """
Parse RabbitMQ config from command-line arguments and environment variables.

**Arguments:**

* ``cmd_args``

  / *Condition*: optional / *Type*: list /

  List of CLI arguments, or None for sys.argv.

* ``service_name``

  / *Condition*: optional / *Type*: str / *Default*: 'Service' /

  Name of the service (used in help text).

**Returns:**

  RabbitMQConfig instance.
      """
      parser = argparse.ArgumentParser(
         description=f'Start the {service_name} service.',
         add_help=False,
      )
      parser.add_argument('--host', type=str, help='The RabbitMQ host')
      parser.add_argument('--port', type=int, help='The RabbitMQ port')
      parser.add_argument('--virtual_host', type=str, help='The RabbitMQ virtual host')
      parser.add_argument('--username', type=str, help='The RabbitMQ username')
      parser.add_argument('--password', type=str, help='The RabbitMQ password')

      if cmd_args is not None:
         args, _ = parser.parse_known_args(cmd_args)
      else:
         args, _ = parser.parse_known_args()

      return cls(
         host=args.host or os.getenv('RABBITMQ_HOST') or 'localhost',
         port=args.port or int(os.getenv('RABBITMQ_PORT', 5672)),
         virtual_host=args.virtual_host or os.getenv('RABBITMQ_VIRTUAL_HOST') or '/',
         username=args.username or os.getenv('RABBITMQ_USERNAME') or 'guest',
         password=args.password or os.getenv('RABBITMQ_PASSWORD') or 'guest',
      )
