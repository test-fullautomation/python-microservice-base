"""
Integration tests for RabbitMQTransportAdapter against a real RabbitMQ broker.
"""

import json
import threading
import time

import pytest

from conftest import requires_rabbitmq, CalculatorService
from MicroserviceBase.adapters.config.rabbitmq_config import RabbitMQConfig
from MicroserviceBase.adapters.transport.rabbitmq_adapter import RabbitMQTransportAdapter
from MicroserviceBase.domain.exceptions import TransportError


@requires_rabbitmq
class TestTransportAdapter:

    def test_connect_disconnect(self, rabbitmq_config):
        """connect() succeeds, connection is open, disconnect() closes it."""
        transport = RabbitMQTransportAdapter(rabbitmq_config)
        transport.connect()
        assert transport.connection is not None
        assert transport.connection.is_open
        transport.disconnect()
        assert transport.connection is None

    def test_connect_bad_host(self):
        """connect() with unreachable host raises TransportError."""
        bad_config = RabbitMQConfig(host='invalid.host.test', port=5672)
        transport = RabbitMQTransportAdapter(bad_config)
        with pytest.raises(TransportError):
            transport.connect()

    def test_publish_and_consume(self, rabbitmq_transport, unique_name):
        """Publish a message, consume it in a thread, verify body received."""
        exchange = f"test_exchange_{unique_name}"
        routing_key = f"test_rk_{unique_name}"
        queue_name = f"test_queue_{unique_name}"
        test_message = {"hello": "world", "id": unique_name}

        received = []
        ready_event = threading.Event()
        done_event = threading.Event()

        def handler(ch, method, props, body):
            received.append(json.loads(body.decode()))
            ch.basic_ack(delivery_tag=method.delivery_tag)
            rabbitmq_transport.stop_consuming()

        def consume_thread():
            rabbitmq_transport.consume(
                service_name=queue_name,
                routing_key=routing_key,
                exchange=exchange,
                handler=handler,
                on_ready=ready_event.set,
            )
            done_event.set()

        t = threading.Thread(target=consume_thread, daemon=True)
        t.start()
        # on_ready fires only after the queue is declared, bound and consuming,
        # so publishing after this point cannot race the binding setup.
        assert ready_event.wait(timeout=5), "Consumer did not become ready"

        # Publish using a separate transport (rpc_call creates its own connection,
        # but publish needs the same connection — use a second transport)
        pub_transport = RabbitMQTransportAdapter(rabbitmq_transport._config)
        pub_transport.connect()
        try:
            # Declare exchange on publisher side too
            ch = pub_transport.connection.channel()
            ch.exchange_declare(exchange=exchange, exchange_type='direct')
            ch.close()
            pub_transport.publish(exchange, routing_key, json.dumps(test_message))
        finally:
            pub_transport.disconnect()

        done_event.wait(timeout=5)
        assert len(received) == 1
        assert received[0] == test_message

    def test_rpc_call_round_trip(self, rabbitmq_config, unique_name):
        """Start CalculatorService consuming, then rpc_call svc_api_add(3,5)."""
        exchange = 'services_request'
        routing_key = f"calc_rk_{unique_name}"
        service_name = f"CalcService_{unique_name}"

        # Create a CalculatorService with real transport
        server_transport = RabbitMQTransportAdapter(rabbitmq_config)
        server_transport.connect()

        # Override routing key for isolation
        svc = CalculatorService(transport=server_transport, registry=None)
        svc._SERVICE_INFO['routing_key'] = routing_key
        svc.name = service_name

        ready_event = threading.Event()

        def serve_thread():
            ready_event.set()
            svc.serve()

        t = threading.Thread(target=serve_thread, daemon=True)
        t.start()
        ready_event.wait(timeout=5)
        time.sleep(0.5)

        # Client RPC call
        client_transport = RabbitMQTransportAdapter(rabbitmq_config)
        client_transport.connect()
        try:
            request_data = {'method': 'svc_api_add', 'args': [3, 5]}
            response = client_transport.rpc_call(
                request_data, exchange, routing_key, timeout=5
            )
            assert response['result'] == 'pass'
            assert response['result_data'] == 8
        finally:
            server_transport.stop_consuming()
            t.join(timeout=5)
            client_transport.disconnect()
            server_transport.disconnect()

    def test_rpc_call_timeout(self, rabbitmq_config, unique_name):
        """rpc_call to non-existent routing key times out with TransportError."""
        transport = RabbitMQTransportAdapter(rabbitmq_config)
        transport.connect()
        try:
            with pytest.raises(TransportError, match="timed out"):
                transport.rpc_call(
                    {'method': 'noop', 'args': []},
                    'services_request',
                    f"nonexistent_rk_{unique_name}",
                    timeout=3,
                )
        finally:
            transport.disconnect()

    def test_stop_consuming(self, rabbitmq_transport, unique_name):
        """stop_consuming() causes the consume loop to exit cleanly."""
        exchange = f"test_exchange_{unique_name}"
        routing_key = f"test_rk_{unique_name}"
        queue_name = f"test_queue_{unique_name}"

        exited = threading.Event()

        def handler(ch, method, props, body):
            pass  # Not expecting messages

        def consume_thread():
            rabbitmq_transport.consume(
                service_name=queue_name,
                routing_key=routing_key,
                exchange=exchange,
                handler=handler,
            )
            exited.set()

        t = threading.Thread(target=consume_thread, daemon=True)
        t.start()
        time.sleep(0.5)

        rabbitmq_transport.stop_consuming()
        assert exited.wait(timeout=5), "Consume loop did not exit after stop_consuming()"
