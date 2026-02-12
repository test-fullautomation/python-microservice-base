"""
Integration tests for AMQPRegistryAdapter against a real RabbitMQ broker.
"""

import json
import threading
import time

import pika
import pytest

from conftest import requires_rabbitmq
from MicroserviceBase.adapters.registry.amqp_registry_adapter import AMQPRegistryAdapter


SAMPLE_SERVICE_INFO = {
    'name': 'TestService',
    'description': 'A test service.',
    'version': '1.0.0',
    'routing_key': 'test_rk',
    'gui_support': False,
    'methods': ['svc_api_test'],
}


@requires_rabbitmq
class TestRegistryAdapter:

    def test_register_publishes_event(self, rabbitmq_registry, unique_name):
        """register() publishes event with state='on' to service_information exchange."""
        # Use unique exchange/queue names so stale messages from prior runs
        # don't interfere, and publish FIRST (durable queue holds the message).
        rabbitmq_registry.EXCHANGE_NAME = f"test_svc_info_{unique_name}"
        rabbitmq_registry.QUEUE_NAME = f"test_svc_queue_{unique_name}"

        rabbitmq_registry.register(SAMPLE_SERVICE_INFO)

        received = []

        def handler(ch, method, props, body):
            event = json.loads(body.decode())
            received.append(event)
            ch.stop_consuming()

        def subscribe_thread():
            rabbitmq_registry.subscribe_to_events(handler)

        t = threading.Thread(target=subscribe_thread, daemon=True)
        t.start()
        t.join(timeout=5)

        assert len(received) == 1
        assert received[0]['state'] == 'on'
        assert received[0]['info']['name'] == 'TestService'

    def test_unregister_publishes_event(self, rabbitmq_registry, unique_name):
        """unregister() publishes event with state='off'."""
        rabbitmq_registry.EXCHANGE_NAME = f"test_svc_info_{unique_name}"
        rabbitmq_registry.QUEUE_NAME = f"test_svc_queue_{unique_name}"

        rabbitmq_registry.unregister(SAMPLE_SERVICE_INFO)

        received = []

        def handler(ch, method, props, body):
            event = json.loads(body.decode())
            received.append(event)
            ch.stop_consuming()

        def subscribe_thread():
            rabbitmq_registry.subscribe_to_events(handler)

        t = threading.Thread(target=subscribe_thread, daemon=True)
        t.start()
        t.join(timeout=5)

        assert len(received) == 1
        assert received[0]['state'] == 'off'
        assert received[0]['info']['name'] == 'TestService'

    def test_notify_update_fanout(self, rabbitmq_registry):
        """notify_update() broadcasts to fanout exchange, subscriber receives full dict."""
        update_data = {'svc1': {'name': 'svc1', 'state': 'on'}}
        received = []
        ready_event = threading.Event()
        # Store a reference to the channel created by subscribe_to_updates
        # so we can stop it from the handler.
        sub_channel = {}

        def update_handler(data):
            received.append(data)
            # stop_consuming on the channel that subscribe_to_updates created
            if sub_channel.get('ch'):
                sub_channel['ch'].stop_consuming()

        def subscribe_thread():
            # Patch subscribe_to_updates to capture the channel before blocking
            original = rabbitmq_registry.subscribe_to_updates

            def patched(handler):
                conn = rabbitmq_registry._get_connection()
                ch = conn.channel()
                ch.exchange_declare(
                    exchange=rabbitmq_registry._update_exchange_name,
                    exchange_type='fanout',
                )
                result = ch.queue_declare(queue='', exclusive=True)
                queue_name = result.method.queue
                ch.queue_bind(
                    exchange=rabbitmq_registry._update_exchange_name,
                    queue=queue_name,
                )

                def _on_message(ch_, method, properties, body):
                    try:
                        data = json.loads(body.decode('utf-8')) if isinstance(body, bytes) else body
                        handler(data)
                    except Exception:
                        pass

                ch.basic_consume(queue=queue_name, on_message_callback=_on_message, auto_ack=True)
                sub_channel['ch'] = ch
                ready_event.set()
                ch.start_consuming()

            patched(update_handler)

        t = threading.Thread(target=subscribe_thread, daemon=True)
        t.start()
        ready_event.wait(timeout=5)
        time.sleep(0.3)

        rabbitmq_registry.notify_update(update_data)

        t.join(timeout=5)
        assert len(received) == 1
        assert received[0] == update_data

    def test_get_update_channel_name(self, rabbitmq_registry, unique_name):
        """Returns the configured update exchange name."""
        expected = f"test_update_{unique_name}"
        assert rabbitmq_registry.get_update_channel_name() == expected

    def test_cleanup(self, rabbitmq_config, unique_name):
        """cleanup() closes channels/connections without error."""
        update_exchange = f"test_cleanup_{unique_name}"
        registry = AMQPRegistryAdapter(rabbitmq_config, update_exchange_name=update_exchange)

        # Start a subscription so there are resources to clean up
        ready_event = threading.Event()

        def handler(ch, method, props, body):
            pass

        def subscribe_thread():
            ready_event.set()
            try:
                registry.subscribe_to_events(handler)
            except Exception:
                pass  # Expected when cleanup closes the channel

        t = threading.Thread(target=subscribe_thread, daemon=True)
        t.start()
        ready_event.wait(timeout=5)
        time.sleep(1)

        # cleanup() should not raise
        registry.cleanup()
        t.join(timeout=5)
