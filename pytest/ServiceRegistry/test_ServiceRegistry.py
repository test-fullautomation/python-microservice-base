"""
Tests for MicroserviceBase domain service_registry.py.

Uses mocked transport/registry — no broker needed.
"""

import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from MicroserviceBase.domain.messages import ResultType
from MicroserviceBase.domain.service_registry import ServiceRegistry


class Test_HandleUpdate:
    """Tests for handle_update() service tracking."""

    def test_handle_update_register(self, service_registry):
        event = {
            'info': {'name': 'SvcA', 'version': '1.0.0', 'routing_key': 'rk_a'},
            'state': 'on',
        }
        service_registry.handle_update(event)
        assert 'SvcA' in service_registry.services_information
        assert service_registry.services_information['SvcA']['version'] == '1.0.0'

    def test_handle_update_unregister(self, service_registry):
        event_on = {
            'info': {'name': 'SvcB', 'version': '1.0.0', 'routing_key': 'rk_b'},
            'state': 'on',
        }
        event_off = {
            'info': {'name': 'SvcB', 'version': '1.0.0', 'routing_key': 'rk_b'},
            'state': 'off',
        }
        service_registry.handle_update(event_on)
        assert 'SvcB' in service_registry.services_information
        service_registry.handle_update(event_off)
        assert 'SvcB' not in service_registry.services_information

    def test_handle_update_ignore_duplicate(self, service_registry):
        event = {
            'info': {'name': 'SvcC', 'version': '1.0.0', 'routing_key': 'rk_c'},
            'state': 'on',
        }
        service_registry.handle_update(event)
        # Re-registering same name should be no-op (original data preserved)
        event2 = {
            'info': {'name': 'SvcC', 'version': '2.0.0', 'routing_key': 'rk_c2'},
            'state': 'on',
        }
        service_registry.handle_update(event2)
        assert service_registry.services_information['SvcC']['version'] == '1.0.0'

    def test_handle_update_ignore_unknown_off(self, service_registry):
        event = {
            'info': {'name': 'UnknownSvc'},
            'state': 'off',
        }
        # Should not raise
        service_registry.handle_update(event)
        assert 'UnknownSvc' not in service_registry.services_information


class Test_GetServicesInfo:
    """Tests for svc_api_get_services_info."""

    def test_get_services_info(self, service_registry):
        event = {
            'info': {'name': 'SvcX', 'version': '1.0.0'},
            'state': 'on',
        }
        service_registry.handle_update(event)
        result = service_registry.svc_api_get_services_info()
        parsed = json.loads(result)
        assert 'SvcX' in parsed

    def test_get_services_info_empty(self, service_registry):
        result = service_registry.svc_api_get_services_info()
        parsed = json.loads(result)
        assert parsed == {}


class Test_IsSpecificRequest:
    """Tests for alias-based specific request detection."""

    def test_is_specific_request_alias(self, service_registry):
        service_registry._alias_dict = {
            'alias_cmd': {
                'Service name': 'SvcTarget',
                'Method name': 'svc_api_do',
                'Arguments': '${input}',
            }
        }
        assert service_registry.is_specific_request('alias_cmd') is True

    def test_is_specific_request_not_alias(self, service_registry):
        assert service_registry.is_specific_request('svc_api_get_version') is False


class Test_AliasSubstitution:
    """Tests for alias argument substitution logic."""

    def test_alias_substitution_single_input(self, service_registry, mock_transport):
        service_registry._alias_dict = {
            'my_alias': {
                'Service name': 'SvcTarget',
                'Method name': 'svc_api_do',
                'Arguments': '710925,17,${input}',
            }
        }
        service_registry.services_information = {
            'SvcTarget': {'name': 'SvcTarget', 'routing_key': 'rk_target'},
        }
        mock_transport.rpc_call.return_value = {'result': 'pass', 'result_data': 'ok'}

        body = {'method': 'my_alias', 'args': ['1']}
        service_registry.handle_alias_request(body)

        call_args = mock_transport.rpc_call.call_args
        request_data = call_args[0][0]
        assert request_data['method'] == 'svc_api_do'
        assert request_data['args'] == ['710925', '17', '1']

    def test_alias_substitution_multiple_inputs(self, service_registry, mock_transport):
        service_registry._alias_dict = {
            'multi_alias': {
                'Service name': 'SvcTarget',
                'Method name': 'svc_api_do',
                'Arguments': '${input},${input}',
            }
        }
        service_registry.services_information = {
            'SvcTarget': {'name': 'SvcTarget', 'routing_key': 'rk_target'},
        }
        mock_transport.rpc_call.return_value = {'result': 'pass', 'result_data': 'ok'}

        body = {'method': 'multi_alias', 'args': ['3', '5']}
        service_registry.handle_alias_request(body)

        call_args = mock_transport.rpc_call.call_args
        request_data = call_args[0][0]
        assert request_data['args'] == ['3', '5']

    def test_alias_substitution_no_input(self, service_registry, mock_transport):
        service_registry._alias_dict = {
            'fixed_alias': {
                'Service name': 'SvcTarget',
                'Method name': 'svc_api_do',
                'Arguments': 'a,b,c',
            }
        }
        service_registry.services_information = {
            'SvcTarget': {'name': 'SvcTarget', 'routing_key': 'rk_target'},
        }
        mock_transport.rpc_call.return_value = {'result': 'pass', 'result_data': 'ok'}

        body = {'method': 'fixed_alias', 'args': []}
        service_registry.handle_alias_request(body)

        call_args = mock_transport.rpc_call.call_args
        request_data = call_args[0][0]
        assert request_data['args'] == ['a', 'b', 'c']

    def test_alias_service_not_found(self, service_registry):
        service_registry._alias_dict = {
            'bad_alias': {
                'Service name': 'MissingSvc',
                'Method name': 'svc_api_do',
                'Arguments': '${input}',
            }
        }
        service_registry.services_information = {}

        body = {'method': 'bad_alias', 'args': ['x']}
        resp = service_registry.handle_alias_request(body)
        assert resp.result == ResultType.EXCEPT.value
        assert 'MissingSvc' in resp.result_data

    def test_alias_forwards_to_service(self, service_registry, mock_transport):
        service_registry._alias_dict = {
            'fwd_alias': {
                'Service name': 'SvcTarget',
                'Method name': 'svc_api_run',
                'Arguments': '${input}',
            }
        }
        service_registry.services_information = {
            'SvcTarget': {'name': 'SvcTarget', 'routing_key': 'rk_target'},
        }
        expected_resp = {'request': 'svc_api_run', 'result': 'pass', 'result_data': 'done'}
        mock_transport.rpc_call.return_value = expected_resp

        body = {'method': 'fwd_alias', 'args': ['val']}
        resp = service_registry.handle_alias_request(body)
        assert resp == expected_resp

        # Verify the transport was called with the right exchange and routing key
        call_args = mock_transport.rpc_call.call_args
        assert call_args[0][1] == 'services_request'  # exchange
        assert call_args[0][2] == 'rk_target'  # routing_key


class Test_RealtimeUpdateExchange:
    """Tests for svc_api_get_realtime_update_exchange."""

    def test_svc_api_get_realtime_update_exchange(self, service_registry):
        exchange = service_registry.svc_api_get_realtime_update_exchange()
        assert isinstance(exchange, str)
        assert len(exchange) > 0
