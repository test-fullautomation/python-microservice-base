"""
Tests for the full status of a failed gRPC call made for the GUI.

A service fails a call with a code, a message and ``google.rpc.Status``
details (``adapters/grpc_bridge/rpc_status.py``); the bridge passes them
to the GUI with the request metadata it adds (``call_metadata`` in
``adapters/ui_bridge/fastapi_bridge.py``). The tests run a real gRPC
server on a loopback port, with descriptors built in code.
"""

import os
import sys
import time
from concurrent import futures

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

grpc = pytest.importorskip("grpc")

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory  # noqa: E402

from MicroserviceBase.adapters.grpc_bridge import GrpcReflectError, rpc_status  # noqa: E402
from MicroserviceBase.adapters.grpc_bridge.reflect_client import _invoke_method  # noqa: E402
from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import BRIDGE_METADATA, call_metadata  # noqa: E402

SERVICE = "demo.v1.Orders"


def _demo_pool():
    """demo.v1.Orders/Put(Item) -> Item, with Item { string id = 1; int32 version = 2; }."""
    F = descriptor_pb2.FieldDescriptorProto
    fd = descriptor_pb2.FileDescriptorProto(name="demo/v1/orders.proto", package="demo.v1", syntax="proto3")
    item = fd.message_type.add(name="Item")
    item.field.add(name="id", number=1, type=F.TYPE_STRING, label=F.LABEL_OPTIONAL)
    item.field.add(name="version", number=2, type=F.TYPE_INT32, label=F.LABEL_OPTIONAL)
    svc = fd.service.add(name="Orders")
    svc.method.add(name="Put", input_type=".demo.v1.Item", output_type=".demo.v1.Item")
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fd)
    return pool


POOL = _demo_pool()
Item = message_factory.GetMessageClass(POOL.FindMessageTypeByName("demo.v1.Item"))


def _rpc(name):
    return message_factory.GetMessageClass(rpc_status._POOL.FindMessageTypeByName("google.rpc." + name))


# Status.details holds the Any of the decoder's own pool, not google.protobuf's.
_rpc_any = message_factory.GetMessageClass(rpc_status._POOL.FindMessageTypeByName("google.protobuf.Any"))


def _any(msg, type_name):
    return _rpc_any(type_url="type.googleapis.com/" + type_name, value=msg.SerializeToString())


def _fail(context, code, message, details):
    status = _rpc("Status")(code=code.value[0], message=message, details=details)
    context.set_trailing_metadata(((rpc_status.DETAILS_KEY, status.SerializeToString()),))
    context.abort(code, message)


def _put(request, context):
    if request.id == "bad":
        bad = _rpc("BadRequest")()
        v = bad.field_violations.add()
        v.field, v.description = "id", "must start with a letter"
        _fail(context, grpc.StatusCode.INVALID_ARGUMENT, "the item is not valid", [_any(bad, "google.rpc.BadRequest")])
    if request.id == "conflict":
        pre = _rpc("PreconditionFailure")()
        v = pre.violations.add()
        v.type, v.subject, v.description = "VERSION", "item/7", "stored version is 4"
        _fail(context, grpc.StatusCode.FAILED_PRECONDITION, "version conflict", [
            _any(pre, "google.rpc.PreconditionFailure"),
            _any(Item(id="7", version=4), "demo.v1.Item"),        # a type of the service's own
            _rpc_any(type_url="type.googleapis.com/x.y.Unknown", value=b"\x01\x02"),
        ])
    if request.id == "plain":
        context.abort(grpc.StatusCode.NOT_FOUND, "no such item")
    if request.id == "slow":
        time.sleep(1.0)
    md = dict(context.invocation_metadata())
    return Item(id="|".join(md.get(k, "") for k in ("x-request-id", "x-mm-user", "tenant")), version=request.version)


@pytest.fixture(scope="module")
def channel():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE, {
        "Put": grpc.unary_unary_rpc_method_handler(_put, request_deserializer=Item.FromString,
                                                   response_serializer=Item.SerializeToString),
    }),))
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    ch = grpc.insecure_channel("127.0.0.1:%d" % port)
    yield ch
    ch.close()
    server.stop(0)


def _call(channel, item_id, call_timeout=None, metadata=None):
    return _invoke_method(channel=channel, pool=POOL, target="test", timeout=5.0,
                          full_service_name=SERVICE, method_name="Put",
                          args_json='{"id": "%s", "version": 3}' % item_id,
                          max_events=10, max_seconds=5.0, call_timeout=call_timeout, metadata=metadata)


class Test_Status:

    def test_field_errors_arrive_decoded(self, channel):
        with pytest.raises(GrpcReflectError) as info:
            _call(channel, "bad")
        e = info.value
        assert e.code == "INVALID_ARGUMENT"
        assert str(e) == "INVALID_ARGUMENT: the item is not valid"
        assert e.details == [{"@type": "google.rpc.BadRequest",
                              "field_violations": [{"field": "id", "description": "must start with a letter"}]}]

    def test_own_types_decode_and_unknown_types_stay_raw(self, channel):
        with pytest.raises(GrpcReflectError) as info:
            _call(channel, "conflict")
        pre, own, unknown = info.value.details
        assert info.value.code == "FAILED_PRECONDITION"
        assert pre["@type"] == "google.rpc.PreconditionFailure"
        assert pre["violations"][0]["type"] == "VERSION"
        assert own == {"@type": "demo.v1.Item", "id": "7", "version": 4}
        assert unknown == {"@type": "x.y.Unknown", "value": "AQI="}

    def test_a_status_without_details(self, channel):
        with pytest.raises(GrpcReflectError) as info:
            _call(channel, "plain")
        assert (info.value.code, info.value.details) == ("NOT_FOUND", [])

    def test_timeout_is_the_callers(self, channel):
        with pytest.raises(GrpcReflectError) as info:
            _call(channel, "slow", call_timeout=0.2)
        assert info.value.code == "DEADLINE_EXCEEDED"

    def test_a_bridge_failure_has_no_code(self, channel):
        with pytest.raises(GrpcReflectError) as info:
            _invoke_method(channel=channel, pool=POOL, target="test", timeout=5.0,
                           full_service_name=SERVICE, method_name="Missing", args_json="{}",
                           max_events=10, max_seconds=5.0)
        assert (info.value.code, info.value.details) == ("", [])


class Test_Metadata:

    def test_the_service_sees_request_id_user_and_caller_keys(self, channel):
        md, rid = call_metadata({"tenant": "lab-3"}, "req-42")
        assert rid == "req-42"
        got = _call(channel, "echo", metadata=md)["result"]["id"].split("|")
        assert got[0] == "req-42"
        assert got[2] == "lab-3"
        assert got[1] == dict(md).get("x-mm-user", "")

    def test_a_missing_or_bad_request_id_is_replaced(self):
        _md, rid = call_metadata({}, "")
        assert len(rid) == 32
        _md, rid = call_metadata({}, "has space")
        assert rid != "has space" and len(rid) == 32

    @pytest.mark.parametrize("key", ["X-Upper", "grpc-timeout", "blob-bin", "x-mm-user", "x-request-id", "a b"])
    def test_reserved_and_bad_keys_are_refused(self, key):
        with pytest.raises(ValueError):
            call_metadata({key: "v"})

    def test_values_must_be_printable(self):
        with pytest.raises(ValueError):
            call_metadata({"note": "line\nbreak"})
        with pytest.raises(ValueError):
            call_metadata({"note": "x" * 1025})

    def test_the_bridge_keys_are_last_and_not_doubled(self):
        md, _rid = call_metadata({"a": "1"})
        keys = [k for k, _v in md]
        assert keys[0] == "a"
        assert [k for k in keys if k in BRIDGE_METADATA] == keys[1:]
