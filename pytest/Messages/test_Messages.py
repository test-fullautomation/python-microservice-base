"""
Tests for MicroserviceBase domain messages (messages.py).
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from MicroserviceBase.domain.messages import ResultType, ServiceRequest, ServiceResponse, ServiceEvent


class Test_ResultType:
    """Tests for the ResultType enum."""

    def test_result_type_values(self):
        assert ResultType.PASS.value == "pass"
        assert ResultType.FAIL.value == "fail"
        assert ResultType.EXCEPT.value == "exception"


class Test_ServiceRequest:
    """Tests for ServiceRequest serialization."""

    def test_service_request_to_dict(self):
        req = ServiceRequest(method="svc_api_add", args=[1, 2])
        d = req.to_dict()
        assert d == {'method': 'svc_api_add', 'args': [1, 2]}

    def test_service_request_to_json(self):
        req = ServiceRequest(method="svc_api_add", args=[1, 2])
        j = req.to_json()
        parsed = json.loads(j)
        assert parsed['method'] == 'svc_api_add'
        assert parsed['args'] == [1, 2]

    def test_service_request_from_dict(self):
        data = {'method': 'svc_api_get_version', 'args': None}
        req = ServiceRequest.from_dict(data)
        assert req.method == 'svc_api_get_version'
        assert req.args is None

    def test_service_request_from_json(self):
        j = '{"method": "svc_api_greet", "args": ["Alice"]}'
        req = ServiceRequest.from_json(j)
        assert req.method == 'svc_api_greet'
        assert req.args == ['Alice']

    def test_service_request_round_trip_json(self):
        original = ServiceRequest(method="svc_api_test", args=["a", "b"])
        restored = ServiceRequest.from_json(original.to_json())
        assert restored.method == original.method
        assert restored.args == original.args

    def test_service_request_no_args(self):
        req = ServiceRequest(method="svc_api_noop")
        assert req.args is None
        d = req.to_dict()
        assert d['args'] is None


class Test_ServiceResponse:
    """Tests for ServiceResponse serialization."""

    def test_service_response_to_dict(self):
        resp = ServiceResponse(request="svc_api_add", result="pass", result_data=42)
        d = resp.to_dict()
        assert d['request'] == 'svc_api_add'
        assert d['result'] == 'pass'
        assert d['result_data'] == 42

    def test_service_response_ordered_dict(self):
        resp = ServiceResponse(request="m", result="pass", result_data="ok")
        d = resp.to_dict()
        keys = list(d.keys())
        # OrderedDict sorted alphabetically
        assert keys == sorted(keys)

    def test_service_response_to_json(self):
        resp = ServiceResponse(request="m", result="pass", result_data="ok")
        j = resp.to_json()
        parsed = json.loads(j)
        assert parsed['request'] == 'm'
        assert parsed['result'] == 'pass'
        assert parsed['result_data'] == 'ok'

    def test_service_response_from_dict(self):
        data = {'request': 'svc_api_get_version', 'result': 'pass', 'result_data': '1.0.0'}
        resp = ServiceResponse.from_dict(data)
        assert resp.request == 'svc_api_get_version'
        assert resp.result == 'pass'
        assert resp.result_data == '1.0.0'

    def test_service_response_from_json(self):
        j = '{"request": "m", "result": "fail", "result_data": "error"}'
        resp = ServiceResponse.from_json(j)
        assert resp.request == 'm'
        assert resp.result == 'fail'
        assert resp.result_data == 'error'

    def test_service_response_get_json(self):
        resp = ServiceResponse(request="m", result="pass", result_data="data")
        assert resp.get_json() == resp.to_json()

    def test_service_response_get_data(self):
        resp = ServiceResponse(request="m", result="pass", result_data={"key": "value"})
        assert resp.get_data() == {"key": "value"}

    def test_service_response_defaults(self):
        resp = ServiceResponse()
        assert resp.request == ""
        assert resp.result == ResultType.PASS.value
        assert resp.result_data == ""

    def test_service_response_round_trip_json(self):
        original = ServiceResponse(request="api", result="pass", result_data=[1, 2, 3])
        restored = ServiceResponse.from_json(original.to_json())
        assert restored.request == original.request
        assert restored.result == original.result
        assert restored.result_data == original.result_data


class Test_ServiceEvent:
    """Tests for ServiceEvent serialization."""

    def test_service_event_to_dict(self):
        event = ServiceEvent(
            service_name="TestSvc",
            state="on",
            info={"name": "TestSvc", "version": "1.0.0"},
        )
        d = event.to_dict()
        assert d['state'] == 'on'
        assert d['info']['name'] == 'TestSvc'
        # to_dict does not include service_name directly
        assert 'service_name' not in d

    def test_service_event_from_dict(self):
        data = {
            'state': 'off',
            'info': {'name': 'MySvc', 'version': '2.0.0'},
        }
        event = ServiceEvent.from_dict(data)
        assert event.service_name == 'MySvc'
        assert event.state == 'off'
        assert event.info == {'name': 'MySvc', 'version': '2.0.0'}

    def test_service_event_from_dict_empty_info(self):
        data = {'state': 'on'}
        event = ServiceEvent.from_dict(data)
        assert event.service_name == ''
        assert event.info == {}

    def test_service_event_round_trip_json(self):
        original = ServiceEvent(
            service_name="Svc",
            state="on",
            info={"name": "Svc", "key": "value"},
        )
        j = original.to_json()
        restored = ServiceEvent.from_json(j)
        assert restored.state == original.state
        assert restored.info == original.info
        assert restored.service_name == 'Svc'
