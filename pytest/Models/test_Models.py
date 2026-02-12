"""
Tests for MicroserviceBase domain models (models.py).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from MicroserviceBase.domain.models import MethodArgument, ServiceMethod, ServiceInfo


class Test_MethodArgument:
    """Tests for the MethodArgument dataclass."""

    def test_method_argument_to_dict(self):
        arg = MethodArgument(
            name="count",
            condition="required",
            type="int",
            default="0",
            description="Number of items",
        )
        d = arg.to_dict()
        assert d == {
            'name': 'count',
            'condition': 'required',
            'type': 'int',
            'default': '0',
            'description': 'Number of items',
        }

    def test_method_argument_from_dict(self):
        data = {
            'name': 'path',
            'condition': 'required',
            'type': 'str',
            'default': '/tmp',
            'description': 'File path',
        }
        arg = MethodArgument.from_dict(data)
        assert arg.to_dict() == data

    def test_method_argument_defaults(self):
        arg = MethodArgument(name="x")
        assert arg.condition is None
        assert arg.type is None
        assert arg.default is None
        assert arg.description == ""

    def test_method_argument_from_dict_defaults(self):
        arg = MethodArgument.from_dict({'name': 'y'})
        assert arg.name == 'y'
        assert arg.condition is None
        assert arg.type is None
        assert arg.default is None
        assert arg.description == ""


class Test_ServiceMethod:
    """Tests for the ServiceMethod dataclass."""

    def test_service_method_to_dict(self):
        arg = MethodArgument(name="a", type="int")
        method = ServiceMethod(name="svc_api_add", arguments=[arg], return_type="int")
        d = method.to_dict()
        assert 'arguments' in d
        assert len(d['arguments']) == 1
        assert d['arguments'][0]['name'] == 'a'
        assert d['return_type'] == 'int'

    def test_service_method_from_dict(self):
        data = {
            'arguments': [{'name': 'x', 'condition': None, 'type': 'str', 'default': None, 'description': ''}],
            'return_type': 'str',
        }
        method = ServiceMethod.from_dict("svc_api_test", data)
        assert method.name == "svc_api_test"
        assert len(method.arguments) == 1
        assert method.arguments[0].name == 'x'
        assert method.return_type == 'str'

    def test_service_method_return_type_excluded_when_none(self):
        method = ServiceMethod(name="svc_api_noop", arguments=[], return_type=None)
        d = method.to_dict()
        assert 'return_type' not in d

    def test_service_method_return_type_included_when_set(self):
        method = ServiceMethod(name="svc_api_get", arguments=[], return_type="dict")
        d = method.to_dict()
        assert d['return_type'] == 'dict'


class Test_ServiceInfo:
    """Tests for the ServiceInfo dataclass."""

    def test_service_info_to_dict(self):
        info = ServiceInfo(
            name="TestService",
            description="A test service",
            version="2.0.0",
            routing_key="test_rk",
            gui_support=True,
        )
        d = info.to_dict()
        assert d['name'] == 'TestService'
        assert d['description'] == 'A test service'
        assert d['version'] == '2.0.0'
        assert d['routing_key'] == 'test_rk'
        assert d['gui_support'] is True

    def test_service_info_from_dict(self):
        data = {
            'name': 'SvcA',
            'version': '3.0.0',
            'gui_support': True,
            'downloadable': True,
        }
        info = ServiceInfo.from_dict(data)
        assert info.name == 'SvcA'
        assert info.version == '3.0.0'
        assert info.gui_support is True
        assert info.downloadable is True
        # Defaults for missing fields
        assert info.description == ''
        assert info.routing_key == ''

    def test_service_info_defaults(self):
        info = ServiceInfo(name="Default")
        assert info.version == "1.0.0"
        assert info.gui_support is False
        assert info.downloadable is False
        assert info.methods == []
        assert info.methods_info == {}
        assert info.description == ""
        assert info.shortdesc == ""
        assert info.group == ""
        assert info.tag == ""

    def test_service_info_round_trip(self):
        original = ServiceInfo(
            name="RoundTrip",
            description="Test round-trip",
            shortdesc="RT",
            group="grp",
            tag="v1",
            version="1.2.3",
            routing_key="rt_key",
            gui_support=True,
            downloadable=True,
            methods=["svc_api_foo"],
            methods_info={},
        )
        d = original.to_dict()
        restored = ServiceInfo.from_dict(d)
        assert restored.name == original.name
        assert restored.version == original.version
        assert restored.gui_support == original.gui_support
        assert restored.methods == original.methods

    def test_service_info_to_dict_with_service_method_objects(self):
        method = ServiceMethod(name="svc_api_test", arguments=[], return_type="str")
        info = ServiceInfo(
            name="MethodTest",
            methods_info={"svc_api_test": method},
        )
        d = info.to_dict()
        assert 'svc_api_test' in d['methods_info']
        assert 'arguments' in d['methods_info']['svc_api_test']
