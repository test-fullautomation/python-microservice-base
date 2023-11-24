from ServiceBase import ServiceBase, ResultType, ResponseMessage
import threading
import pika
import json
import uuid
from signal import *


class ServiceRegistry(ServiceBase):
   _SERVICE_INFO = {
      'name': 'ServiceRegistry',
      'description': 'One-stop service providing complete details on all system services as requested by users.',
      'shortdesc': 'Registry service',
      'group': '',
      'tag': '',
      'version': '1.0.0',
      'routing_key': 'abcxyz',
      'gui_support': False,
      # Other details
      'methods': []
   }

   def __init__(self, **conn_params):
      super(ServiceRegistry, self).__init__(**conn_params)
      self.services_information = dict()
      self.realtime_update_exchange = 'registry_update' + str(uuid.uuid4())
      thread_worker = threading.Thread(target=self.receive_services_information)
      thread_worker.daemon = True
      thread_worker.name = "recv_services_infor"
      thread_worker.start()

   def __del__(self):
      connection = pika.BlockingConnection(pika.ConnectionParameters(**self._kw_args))
      channel = connection.channel()

      channel.exchange_delete(exchange=self.realtime_update_exchange)
      connection.close()
      super(ServiceRegistry, self).__del__()

   def receive_services_information(self):
      connection = pika.BlockingConnection(pika.ConnectionParameters(**self._kw_args))
      channel = connection.channel()

      exchange_name = 'service_information'

      channel.exchange_declare(exchange=exchange_name, exchange_type='topic')

      # Ensure the queue is durable and named to be reused
      queue_name = 'service_infor_queue'
      channel.queue_declare(queue=queue_name, durable=True)

      # Bind the queue to specific routing keys
      channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key='service.information')

      print(" [*] Waiting for updates. To exit press CTRL+C")

      channel.basic_consume(queue=queue_name, on_message_callback=self.handle_update, auto_ack=True)

      channel.start_consuming()

   def handle_update(self, ch, method, properties, body):
      if isinstance(body, bytes):
         service_information = json.loads(body.decode('utf-8'))

      if service_information['info']['name'] not in self.services_information and service_information['state'] == "on":
         self.services_information[service_information['info']['name']] = service_information['info']
      elif service_information['info']['name'] in self.services_information and service_information['state'] == "off":
         del self.services_information[service_information['info']['name']]

      self.notify_updates()
      print(" [x] Received update:", service_information)

   def notify_updates(self):
      connection = pika.BlockingConnection(pika.ConnectionParameters(**self._kw_args))
      channel = connection.channel()

      channel.exchange_declare(exchange=self.realtime_update_exchange, exchange_type='fanout')

      # Publish updates to the 'updates' topic
      update_info = json.dumps(self.services_information)
      channel.basic_publish(exchange=self.realtime_update_exchange, routing_key='', body=update_info)

      print("Update info sent to RabbitMQ")
      connection.close()

   def svc_api_get_services_info(self):
      services_json = json.dumps(self.services_information)
      return services_json

   def svc_api_get_realtime_update_exchange(self):
      return self.realtime_update_exchange


def signal_handler(sig, frame, obj):
   # This function will be called when a SIGINT signal (Ctrl+C) is received
   print("Ctrl+C pressed - Cleaning up...")
   # Perform any necessary cleanup here
   # For example, call the cleanup method of the object
   del obj
   # Exit the program
   exit(0)


if __name__ == '__main__':
   svc = ServiceRegistry(host='localhost')
   # Register the signal handler for SIGINT (Ctrl+C)
   for sign in (SIGABRT, SIGILL, SIGINT, SIGSEGV, SIGTERM):
      signal(sign, lambda sig, frame: signal_handler(sig, frame, svc))
   svc.serve()
