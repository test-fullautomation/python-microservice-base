"""
End-to-end integration tests: CalculatorService serving real RPC requests through RabbitMQ.
"""

import json
import threading
import time

import pytest

from conftest import requires_rabbitmq, CalculatorService
from MicroserviceBase.adapters.transport.rabbitmq_adapter import RabbitMQTransportAdapter
from MicroserviceBase.adapters.registry.amqp_registry_adapter import AMQPRegistryAdapter


@requires_rabbitmq
class TestEndToEnd:

    @pytest.fixture(autouse=True)
    def _setup_service(self, rabbitmq_config, unique_name):
        """Set up a CalculatorService with real transport, serve in a thread."""
        self.config = rabbitmq_config
        self.unique_name = unique_name
        self.exchange = 'services_request'
        self.routing_key = f"e2e_calc_rk_{unique_name}"
        self.service_name = f"E2ECalcService_{unique_name}"

        # Server transport + service
        self.server_transport = RabbitMQTransportAdapter(rabbitmq_config)
        self.server_transport.connect()

        self.service = CalculatorService(transport=self.server_transport, registry=None)
        self.service._SERVICE_INFO['routing_key'] = self.routing_key
        self.service.name = self.service_name

        ready = threading.Event()

        def serve():
            ready.set()
            self.service.serve()

        self.serve_thread = threading.Thread(target=serve, daemon=True)
        self.serve_thread.start()
        ready.wait(timeout=5)
        time.sleep(0.5)

        # Client transport for RPC calls
        self.client_transport = RabbitMQTransportAdapter(rabbitmq_config)
        self.client_transport.connect()

        yield

        self.server_transport.stop_consuming()
        self.serve_thread.join(timeout=5)
        self.client_transport.disconnect()
        self.server_transport.disconnect()

    def _rpc(self, method, args=None, timeout=5):
        """Helper: send RPC request and return response dict."""
        request = {'method': method, 'args': args or []}
        return self.client_transport.rpc_call(
            request, self.exchange, self.routing_key, timeout=timeout
        )

    def test_service_register_and_discover(self, rabbitmq_config, unique_name):
        """CalculatorService registers, registry adapter receives the event."""
        update_exchange = f"test_e2e_update_{unique_name}"
        registry = AMQPRegistryAdapter(rabbitmq_config, update_exchange_name=update_exchange)

        # Use unique exchange/queue to avoid stale messages; publish first.
        registry.EXCHANGE_NAME = f"test_e2e_svc_info_{unique_name}"
        registry.QUEUE_NAME = f"test_e2e_svc_queue_{unique_name}"

        svc_registry = AMQPRegistryAdapter(rabbitmq_config)
        svc_registry.EXCHANGE_NAME = registry.EXCHANGE_NAME
        svc_registry.QUEUE_NAME = registry.QUEUE_NAME
        svc_registry.register(self.service.get_service_info_dict())

        received = []

        def handler(ch, method, props, body):
            event = json.loads(body.decode())
            received.append(event)
            ch.stop_consuming()

        def subscribe_thread():
            registry.subscribe_to_events(handler)

        t = threading.Thread(target=subscribe_thread, daemon=True)
        t.start()
        t.join(timeout=5)
        registry.cleanup()

        assert len(received) == 1
        assert received[0]['state'] == 'on'
        assert received[0]['info']['name'] == 'CalculatorService'

    def test_service_rpc_add(self):
        """RPC svc_api_add(10, 20) returns 30."""
        response = self._rpc('svc_api_add', [10, 20])
        assert response['result'] == 'pass'
        assert response['result_data'] == 30

    def test_service_rpc_get_version(self):
        """RPC svc_api_get_version returns '2.0.0'."""
        response = self._rpc('svc_api_get_version')
        assert response['result'] == 'pass'
        assert response['result_data'] == '2.0.0'

    def test_service_rpc_unknown_method(self):
        """RPC to non-existent method returns fail with 'Non-supported request'."""
        response = self._rpc('svc_api_nonexistent')
        assert response['result'] == 'fail'
        assert response['result_data'] == 'Non-supported request'
