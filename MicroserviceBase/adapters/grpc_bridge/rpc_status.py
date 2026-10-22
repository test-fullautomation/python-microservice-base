"""The full status of a failed gRPC call: code, message and decoded details.

A service that says more than a message sends a ``google.rpc.Status`` in
the ``grpc-status-details-bin`` trailer, with ``google.protobuf.Any``
details such as ``google.rpc.BadRequest`` (which fields are wrong) or
``google.rpc.PreconditionFailure`` ("version conflict", "not allowed in
this state").  :func:`status_of` turns that into plain JSON for the GUI.

The ``google.rpc`` messages are described here in code, so the bridge
needs no ``googleapis-common-protos``.  A detail of a type the service
defines itself is decoded when the service's descriptor pool knows it;
any other detail comes back as its type name and base64 bytes.
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

import grpc
from google.protobuf import any_pb2, descriptor_pb2, descriptor_pool, duration_pb2, message_factory
from google.protobuf.json_format import MessageToDict

DETAILS_KEY = "grpc-status-details-bin"

_F = descriptor_pb2.FieldDescriptorProto
_STRING, _INT32, _MESSAGE = _F.TYPE_STRING, _F.TYPE_INT32, _F.TYPE_MESSAGE
_REPEATED = _F.LABEL_REPEATED

# message -> [(field, number, type, type_name or "", repeated)], after
# google/rpc/status.proto and google/rpc/error_details.proto.
_MESSAGES = {
    "Status": [("code", 1, _INT32, "", False), ("message", 2, _STRING, "", False),
               ("details", 3, _MESSAGE, ".google.protobuf.Any", True)],
    "ErrorInfo": [("reason", 1, _STRING, "", False), ("domain", 2, _STRING, "", False),
                  ("metadata", 3, _MESSAGE, ".google.rpc.ErrorInfo.MetadataEntry", True)],
    "RetryInfo": [("retry_delay", 1, _MESSAGE, ".google.protobuf.Duration", False)],
    "DebugInfo": [("stack_entries", 1, _STRING, "", True), ("detail", 2, _STRING, "", False)],
    "QuotaFailure": [("violations", 1, _MESSAGE, ".google.rpc.QuotaFailure.Violation", True)],
    "PreconditionFailure": [("violations", 1, _MESSAGE, ".google.rpc.PreconditionFailure.Violation", True)],
    "BadRequest": [("field_violations", 1, _MESSAGE, ".google.rpc.BadRequest.FieldViolation", True)],
    "RequestInfo": [("request_id", 1, _STRING, "", False), ("serving_data", 2, _STRING, "", False)],
    "ResourceInfo": [("resource_type", 1, _STRING, "", False), ("resource_name", 2, _STRING, "", False),
                     ("owner", 3, _STRING, "", False), ("description", 4, _STRING, "", False)],
    "Help": [("links", 1, _MESSAGE, ".google.rpc.Help.Link", True)],
    "LocalizedMessage": [("locale", 1, _STRING, "", False), ("message", 2, _STRING, "", False)],
}
_NESTED = {
    "ErrorInfo": [("MetadataEntry", [("key", 1, _STRING, "", False), ("value", 2, _STRING, "", False)], True)],
    "QuotaFailure": [("Violation", [("subject", 1, _STRING, "", False), ("description", 2, _STRING, "", False)], False)],
    "PreconditionFailure": [("Violation", [("type", 1, _STRING, "", False), ("subject", 2, _STRING, "", False),
                                           ("description", 3, _STRING, "", False)], False)],
    "BadRequest": [("FieldViolation", [("field", 1, _STRING, "", False), ("description", 2, _STRING, "", False),
                                       ("reason", 3, _STRING, "", False)], False)],
    "Help": [("Link", [("description", 1, _STRING, "", False), ("url", 2, _STRING, "", False)], False)],
}


def _add_fields(msg, fields) -> None:
    for name, number, ftype, type_name, repeated in fields:
        f = msg.field.add(name=name, number=number, type=ftype,
                          label=_REPEATED if repeated else _F.LABEL_OPTIONAL)
        if type_name:
            f.type_name = type_name


def _build_pool() -> descriptor_pool.DescriptorPool:
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(any_pb2.DESCRIPTOR.serialized_pb)
    pool.AddSerializedFile(duration_pb2.DESCRIPTOR.serialized_pb)
    fd = descriptor_pb2.FileDescriptorProto(
        name="microservicebase/bridge/google_rpc_status.proto", package="google.rpc", syntax="proto3",
        dependency=["google/protobuf/any.proto", "google/protobuf/duration.proto"])
    for name, fields in _MESSAGES.items():
        msg = fd.message_type.add(name=name)
        _add_fields(msg, fields)
        for nested_name, nested_fields, is_map in _NESTED.get(name, []):
            nested = msg.nested_type.add(name=nested_name)
            _add_fields(nested, nested_fields)
            if is_map:
                nested.options.map_entry = True
    pool.Add(fd)
    return pool


_POOL = _build_pool()
_STATUS = message_factory.GetMessageClass(_POOL.FindMessageTypeByName("google.rpc.Status"))


def _detail(any_msg, pools) -> Dict[str, Any]:
    type_name = any_msg.type_url.rsplit("/", 1)[-1]
    for pool in pools:
        try:
            desc = pool.FindMessageTypeByName(type_name)
        except KeyError:
            continue
        try:
            msg = message_factory.GetMessageClass(desc).FromString(any_msg.value)
            # The type's own pool, so an Any inside the detail resolves too.
            out = MessageToDict(msg, preserving_proto_field_name=True, descriptor_pool=pool)
        except Exception:   # noqa: BLE001 -- bytes or contents that do not convert: fall through to raw
            break
        # Well-known types such as Duration convert to a string, not an object.
        if not isinstance(out, dict):
            break
        out["@type"] = type_name
        return out
    return {"@type": type_name, "value": base64.b64encode(any_msg.value).decode("ascii")}


def status_of(exc: grpc.RpcError, pool: Optional[descriptor_pool.DescriptorPool] = None) -> Dict[str, Any]:
    """``{"code": "INVALID_ARGUMENT", "message": str, "details": [dict, ...]}`` of a failed call.

    ``pool`` is the called service's descriptor pool, for details of its
    own types.  A call without a status trailer has ``details == []``.
    """
    code = exc.code() if hasattr(exc, "code") else None
    message = exc.details() if hasattr(exc, "details") else str(exc)
    out: Dict[str, Any] = {"code": code.name if code is not None else "UNKNOWN",
                           "message": message or "", "details": []}
    try:
        trailers = exc.trailing_metadata() if hasattr(exc, "trailing_metadata") else None
    except Exception:   # noqa: BLE001 -- a channel error has no trailers
        trailers = None
    raw = next((v for k, v in (trailers or ()) if k == DETAILS_KEY), None)
    if not raw:
        return out
    try:
        status = _STATUS.FromString(raw)
    except Exception:   # noqa: BLE001 -- a broken trailer costs the details, not the error
        return out
    pools: List[descriptor_pool.DescriptorPool] = [_POOL] + ([pool] if pool is not None else [])
    out["details"] = [_detail(d, pools) for d in status.details]
    return out
