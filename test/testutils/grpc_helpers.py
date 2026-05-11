# **************************************************************************************************************
#
#  Copyright 2020-2026 Robert Bosch GmbH
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
# **************************************************************************************************************
#
# grpc_helpers.py
#
# Reflection-driven gRPC client used by the L4 / L5 runtime test cases.
# Resolves a service via Consul, connects to its gRPC port, lists methods
# through reflection, and invokes a method with a JSON-shaped request.
#
# Mirrors what the FastAPI bridge's GrpcReflectClient does, minus the GUI.
#
# 10.05.2026
#
# --------------------------------------------------------------------------------------------------------------

import json
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------------------------------------------

def grpc_libs_available():
    """True if grpcio + grpcio-reflection are importable in this venv."""
    try:
        import grpc                                                 # noqa: F401
        from grpc_reflection.v1alpha import reflection_pb2_grpc     # noqa: F401
        return True
    except ImportError:
        return False


# --------------------------------------------------------------------------------------------------------------

def list_services_via_reflection(target):
    """Return the list of gRPC service FQNs the server at ``target``
    (host:port) advertises through reflection.
    """
    import grpc
    from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

    channel = grpc.insecure_channel(target)
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    request = reflection_pb2.ServerReflectionRequest(list_services="")
    responses = stub.ServerReflectionInfo(iter([request]))
    services = []
    for resp in responses:
        if resp.HasField("list_services_response"):
            for svc in resp.list_services_response.service:
                services.append(svc.name)
    channel.close()
    return services


# --------------------------------------------------------------------------------------------------------------

def invoke_unary(target, method_fqn, request_dict, timeout=5.0):
    """Call a unary gRPC method by FQN with reflection-derived stubs.

    ``method_fqn`` is ``"<package>.<service>.<method>"``.  Builds the
    request message dynamically from the protobuf schema obtained via
    reflection, populates it from ``request_dict``, calls, and returns
    the response message converted back to a Python dict.
    """
    import grpc
    from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
    from google.protobuf import descriptor_pool, message_factory, descriptor_pb2
    from google.protobuf.json_format import ParseDict, MessageToDict

    pkg_svc, _, method_name = method_fqn.rpartition(".")
    if not pkg_svc or not method_name:
        raise ValueError(f"method_fqn must be <package>.<svc>.<method>, got {method_fqn!r}")

    channel = grpc.insecure_channel(target)
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    # Pull the file descriptor for the containing service
    req = reflection_pb2.ServerReflectionRequest(file_containing_symbol=pkg_svc)
    responses = stub.ServerReflectionInfo(iter([req]))
    pool = descriptor_pool.DescriptorPool()
    file_desc_protos = []
    for resp in responses:
        if resp.HasField("file_descriptor_response"):
            for fd_bytes in resp.file_descriptor_response.file_descriptor_proto:
                fd_proto = descriptor_pb2.FileDescriptorProto()
                fd_proto.ParseFromString(fd_bytes)
                file_desc_protos.append(fd_proto)

    # Add files to pool, dependencies first.  This is naive (assumes the
    # reflection response order is OK) — fine for single-service tests.
    for fd_proto in file_desc_protos:
        try:
            pool.Add(fd_proto)
        except Exception:
            # already added (when reflection echoes shared deps)
            pass

    svc_desc = pool.FindServiceByName(pkg_svc)
    method_desc = svc_desc.FindMethodByName(method_name)
    factory = message_factory.MessageFactory(pool)
    request_cls = factory.GetPrototype(method_desc.input_type)
    response_cls = factory.GetPrototype(method_desc.output_type)

    request_msg = request_cls()
    if request_dict:
        ParseDict(request_dict, request_msg)

    # Build the unary-unary callable manually
    method_path = f"/{pkg_svc}/{method_name}"
    callable_ = channel.unary_unary(
        method_path,
        request_serializer=lambda m: m.SerializeToString(),
        response_deserializer=lambda b: response_cls.FromString(b),
    )

    response = callable_(request_msg, timeout=timeout)
    channel.close()
    return MessageToDict(response, preserving_proto_field_name=True)


# --------------------------------------------------------------------------------------------------------------
