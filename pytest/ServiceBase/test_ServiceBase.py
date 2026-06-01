"""
Tests for MicroserviceBase domain service_base.py.

Uses the CalculatorService fixture from conftest.py — no broker needed.
"""

import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from MicroserviceBase.domain.messages import ResultType
from MicroserviceBase.domain.service_base import ServiceBase


class Test_ApiDiscovery:
    """Tests for svc_api_* method discovery."""

    def test_api_discovery(self, calculator_service):
        api_dict = calculator_service.get_svc_api_methods_dict()
        assert 'svc_api_add' in api_dict
        assert 'svc_api_multiply' in api_dict
        assert 'svc_api_greet' in api_dict
        assert 'svc_api_get_version' in api_dict

    def test_api_discovery_filters_non_api(self, calculator_service):
        api_dict = calculator_service.get_svc_api_methods_dict()
        assert '_private_method' not in api_dict

    def test_internal_methods_hidden_from_service_info(self, calculator_service):
        methods = calculator_service._SERVICE_INFO['methods']
        # Internal methods like svc_api_shutdown should not be published
        assert 'svc_api_shutdown' not in methods
        # But they should still be dispatchable
        assert 'svc_api_shutdown' in calculator_service._api_dict

    def test_gui_methods_filtered_when_no_gui(self, calculator_service):
        assert calculator_service._SERVICE_INFO['gui_support'] is False
        api_dict = calculator_service.get_svc_api_methods_dict()
        assert 'svc_api_get_gui_files' not in api_dict

    def test_service_info_methods_populated(self, calculator_service):
        methods = calculator_service._SERVICE_INFO['methods']
        assert 'svc_api_add' in methods
        assert 'svc_api_multiply' in methods
        assert 'svc_api_greet' in methods
        assert 'svc_api_get_version' in methods


class Test_DispatchRequest:
    """Tests for dispatch_request() domain logic."""

    def test_dispatch_request_no_args(self, calculator_service):
        body = {'method': 'svc_api_get_version', 'args': None}
        resp = calculator_service.dispatch_request(body)
        assert resp.result == ResultType.PASS.value
        assert resp.result_data == '2.0.0'
        assert resp.request == 'svc_api_get_version'

    def test_dispatch_request_with_args(self, calculator_service):
        body = {'method': 'svc_api_add', 'args': [3, 5]}
        resp = calculator_service.dispatch_request(body)
        assert resp.result == ResultType.PASS.value
        assert resp.result_data == 8

    def test_dispatch_request_string_arg(self, calculator_service):
        body = {'method': 'svc_api_greet', 'args': "World"}
        resp = calculator_service.dispatch_request(body)
        assert resp.result == ResultType.PASS.value
        assert resp.result_data == "Hello, World!"

    def test_dispatch_request_unknown_method(self, calculator_service):
        body = {'method': 'svc_api_nonexistent', 'args': None}
        resp = calculator_service.dispatch_request(body)
        assert resp.result_data == "Non-supported request"
        assert resp.result == ResultType.FAIL.value

    def test_dispatch_request_exception(self, calculator_service):
        body = {'method': 'svc_api_fail', 'args': None}
        resp = calculator_service.dispatch_request(body)
        assert resp.result == ResultType.EXCEPT.value
        assert "intentional error" in resp.result_data

    def test_dispatch_request_bytes_response(self, calculator_service):
        body = {'method': 'svc_api_bytes', 'args': None}
        resp = calculator_service.dispatch_request(body)
        assert resp.result == ResultType.PASS.value
        decoded = base64.b64decode(resp.result_data)
        assert decoded == b"\x00\x01\x02\x03"

    def test_dispatch_request_empty_list_args(self, calculator_service):
        body = {'method': 'svc_api_get_version', 'args': []}
        resp = calculator_service.dispatch_request(body)
        assert resp.result == ResultType.PASS.value
        assert resp.result_data == '2.0.0'


class Test_CreateRequestData:
    """Tests for the static create_request_data method."""

    def test_create_request_data(self):
        data = ServiceBase.create_request_data("svc_api_add", [1, 2])
        assert data == {'method': 'svc_api_add', 'args': [1, 2]}

    def test_create_request_data_no_args(self):
        data = ServiceBase.create_request_data("svc_api_get_version", None)
        assert data == {'method': 'svc_api_get_version', 'args': None}


class Test_ParseDocstring:
    """Tests for docstring parsing."""

    def test_parse_docstring_with_args(self, calculator_service):
        docstring = calculator_service.svc_api_add.__doc__
        result = calculator_service.parse_docstring(docstring)
        assert 'arguments' in result
        args = result['arguments']
        assert len(args) == 2
        assert args[0]['name'] == 'a'
        assert args[1]['name'] == 'b'

    def test_parse_docstring_with_return_type(self, calculator_service):
        docstring = calculator_service.svc_api_add.__doc__
        result = calculator_service.parse_docstring(docstring)
        assert 'return_type' in result

    def test_parse_docstring_empty(self, calculator_service):
        result = calculator_service.parse_docstring("")
        assert result.get('arguments', []) == []


class Test_RegisterService:
    """Tests for service registration."""

    def test_register_service_calls_registry(self, calculator_service, mock_registry):
        calculator_service.register_service()
        mock_registry.register.assert_called_once_with(calculator_service._SERVICE_INFO)

    def test_register_service_no_registry(self, mock_transport):
        svc = ServiceBase(transport=mock_transport, registry=None)
        # Should not raise
        svc.register_service()

    def test_unregister_service_calls_registry(self, calculator_service, mock_registry):
        calculator_service.unregister_service()
        mock_registry.unregister.assert_called_once_with(calculator_service._SERVICE_INFO)


class Test_SvcApiGetVersion:
    """Tests for svc_api_get_version."""

    def test_svc_api_get_version(self, calculator_service):
        assert calculator_service.svc_api_get_version() == '2.0.0'
