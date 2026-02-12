"""
Shared fixtures for MicroserviceBase unit tests.
"""

import os
import sys
import uuid
from unittest.mock import MagicMock

import pytest

# Ensure the project root is on sys.path so we can import MicroserviceBase
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from MicroserviceBase.ports.transport import TransportPort
from MicroserviceBase.ports.registry import ServiceRegistryPort
from MicroserviceBase.domain.service_base import ServiceBase
from MicroserviceBase.domain.service_registry import ServiceRegistry


@pytest.fixture
def mock_transport():
    """A MagicMock spec'd to TransportPort (avoids needing RabbitMQ)."""
    return MagicMock(spec=TransportPort)


@pytest.fixture
def mock_registry():
    """A MagicMock spec'd to ServiceRegistryPort."""
    mock = MagicMock(spec=ServiceRegistryPort)
    mock.get_update_channel_name.return_value = 'test_registry_update'
    return mock


class CalculatorService(ServiceBase):
    """Concrete ServiceBase subclass for testing."""

    _SERVICE_INFO = {
        'name': 'CalculatorService',
        'description': 'A test calculator service.',
        'shortdesc': 'Calculator',
        'group': 'test',
        'tag': 'test',
        'version': '2.0.0',
        'routing_key': 'calculator_rk',
        'gui_support': False,
        'downloadable': False,
        'methods': [],
        'methods_info': {},
    }

    def svc_api_add(self, a, b):
        """
Add two numbers.

**Arguments:**

* ``a``

  / *Condition*: required / *Type*: int /

  First operand.

* ``b``

  / *Condition*: required / *Type*: int /

  Second operand.

**Returns:**

  / *Type*: int /

  Sum of a and b.
        """
        return int(a) + int(b)

    def svc_api_multiply(self, a, b):
        """
Multiply two numbers.

**Arguments:**

* ``a``

  / *Condition*: required / *Type*: int /

  First operand.

* ``b``

  / *Condition*: required / *Type*: int /

  Second operand.

**Returns:**

  / *Type*: int /

  Product of a and b.
        """
        return int(a) * int(b)

    def svc_api_greet(self, name):
        """
Greet someone by name.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  The name to greet.

**Returns:**

  / *Type*: str /

  A greeting string.
        """
        return f"Hello, {name}!"

    def svc_api_fail(self):
        """
A method that always raises an exception (for testing).
        """
        raise ValueError("intentional error")

    def svc_api_bytes(self):
        """
A method that returns bytes (for testing base64 encoding).
        """
        return b"\x00\x01\x02\x03"

    def _private_method(self):
        """This should NOT appear in API discovery."""
        pass


@pytest.fixture
def calculator_service(mock_transport, mock_registry):
    """A CalculatorService instance with mocked transport/registry."""
    return CalculatorService(transport=mock_transport, registry=mock_registry)


@pytest.fixture
def service_registry(mock_transport, mock_registry, tmp_path):
    """A ServiceRegistry instance with mocked transport/registry and temp alias file."""
    # Create an empty alias.json so the registry doesn't warn
    alias_path = str(tmp_path / "alias.json")
    with open(alias_path, 'w') as f:
        f.write('{}')
    old_path = ServiceRegistry.ALIAS_CONF_PATH
    ServiceRegistry.ALIAS_CONF_PATH = alias_path
    reg = ServiceRegistry(transport=mock_transport, registry=mock_registry)
    yield reg
    ServiceRegistry.ALIAS_CONF_PATH = old_path


# ---------------------------------------------------------------------------
#  RabbitMQ integration-test helpers
# ---------------------------------------------------------------------------

from MicroserviceBase.adapters.config.rabbitmq_config import RabbitMQConfig
from MicroserviceBase.adapters.transport.rabbitmq_adapter import RabbitMQTransportAdapter
from MicroserviceBase.adapters.registry.amqp_registry_adapter import AMQPRegistryAdapter


def _check_rabbitmq():
    """Try connecting to RabbitMQ; return True if available."""
    try:
        import pika
        config = RabbitMQConfig(
            host=os.getenv('RABBITMQ_HOST', 'localhost'),
            port=int(os.getenv('RABBITMQ_PORT', 5672)),
            username=os.getenv('RABBITMQ_USERNAME', 'guest'),
            password=os.getenv('RABBITMQ_PASSWORD', 'guest'),
        )
        conn = pika.BlockingConnection(
            pika.ConnectionParameters(**config.to_connection_params())
        )
        conn.close()
        return True
    except Exception:
        return False


RABBITMQ_AVAILABLE = _check_rabbitmq()
requires_rabbitmq = pytest.mark.skipif(
    not RABBITMQ_AVAILABLE, reason="RabbitMQ not available"
)


@pytest.fixture
def rabbitmq_config():
    """RabbitMQConfig from env vars or defaults."""
    return RabbitMQConfig(
        host=os.getenv('RABBITMQ_HOST', 'localhost'),
        port=int(os.getenv('RABBITMQ_PORT', 5672)),
        username=os.getenv('RABBITMQ_USERNAME', 'guest'),
        password=os.getenv('RABBITMQ_PASSWORD', 'guest'),
    )


@pytest.fixture
def rabbitmq_transport(rabbitmq_config):
    """Connected RabbitMQTransportAdapter; disconnects on teardown."""
    transport = RabbitMQTransportAdapter(rabbitmq_config)
    transport.connect()
    yield transport
    transport.disconnect()


@pytest.fixture
def rabbitmq_registry(rabbitmq_config, unique_name):
    """AMQPRegistryAdapter with a unique update exchange; cleans up on teardown."""
    update_exchange = f"test_update_{unique_name}"
    registry = AMQPRegistryAdapter(rabbitmq_config, update_exchange_name=update_exchange)
    yield registry
    registry.cleanup()


@pytest.fixture
def unique_name():
    """UUID-based unique name for test isolation (queues, exchanges)."""
    return uuid.uuid4().hex[:12]
