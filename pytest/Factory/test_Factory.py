"""
Tests for MicroserviceBase factory.py.

Tests factory error paths and UI bridge creation (mocking external adapters).
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from MicroserviceBase.factory import create_transport, create_registry, create_ui_bridge


class Test_CreateTransport:
    """Tests for create_transport factory."""

    def test_create_transport_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown transport type"):
            create_transport(transport_type='redis')

    @patch('MicroserviceBase.factory.RabbitMQConfig')
    @patch('MicroserviceBase.factory.RabbitMQTransportAdapter')
    def test_create_transport_rabbitmq(self, mock_adapter_cls, mock_config_cls):
        mock_config = MagicMock()
        mock_config_cls.from_cmd_args.return_value = mock_config
        mock_adapter = MagicMock()
        mock_adapter_cls.return_value = mock_adapter

        result = create_transport(transport_type='rabbitmq', cmd_args=['--host', 'localhost'])
        mock_adapter.connect.assert_called_once()
        assert result is mock_adapter

    @patch('MicroserviceBase.factory.EventBusConfig')
    @patch('MicroserviceBase.factory.EventBusTransportAdapter')
    def test_create_transport_eventbus(self, mock_adapter_cls, mock_config_cls):
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config
        mock_adapter = MagicMock()
        mock_adapter_cls.return_value = mock_adapter

        result = create_transport(transport_type='eventbus', config_path='/tmp/config.json')
        mock_adapter.connect.assert_called_once()
        assert result is mock_adapter


class Test_CreateRegistry:
    """Tests for create_registry factory."""

    def test_create_registry_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown transport type"):
            create_registry(transport_type='redis')

    @patch('MicroserviceBase.factory.RabbitMQConfig')
    @patch('MicroserviceBase.factory.AMQPRegistryAdapter')
    def test_create_registry_rabbitmq(self, mock_adapter_cls, mock_config_cls):
        mock_config = MagicMock()
        mock_config_cls.from_cmd_args.return_value = mock_config
        mock_adapter = MagicMock()
        mock_adapter_cls.return_value = mock_adapter

        result = create_registry(transport_type='rabbitmq', cmd_args=['--host', 'localhost'])
        assert result is mock_adapter


class Test_CreateUiBridge:
    """Tests for create_ui_bridge factory."""

    def test_create_ui_bridge_fastapi(self):
        """Delegates to the GUI's bridge package (microservice-gui repo)."""
        mock_bridge = MagicMock()
        fake = MagicMock()
        fake.create_ui_bridge.return_value = mock_bridge
        with patch.dict(sys.modules, {'microservice_gui_bridge': fake}):
            result = create_ui_bridge(bridge_type='fastapi', host='0.0.0.0', port=9000)
        assert result is mock_bridge
        fake.create_ui_bridge.assert_called_once_with('fastapi', host='0.0.0.0', port=9000,
                                                      allowed_origins=None)

    def test_create_ui_bridge_without_the_bridge_package(self):
        with patch.dict(sys.modules, {'microservice_gui_bridge': None}):
            with pytest.raises(ImportError, match="microservice-gui-bridge"):
                create_ui_bridge(bridge_type='fastapi')

    def test_create_ui_bridge_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown UI bridge type"):
            create_ui_bridge(bridge_type='flask')
