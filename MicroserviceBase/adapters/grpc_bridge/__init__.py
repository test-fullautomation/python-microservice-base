"""gRPC bridge adapter — dynamic method discovery and invocation.

Exposes :class:`GrpcReflectClient` used by the FastAPI bridge to let the
GUI enumerate and call methods on any gRPC service registered in Consul,
without requiring the bridge to know the service's ``.proto`` ahead of
time.  All type information is obtained at runtime via the standard
`gRPC Server Reflection Protocol`_.

.. _gRPC Server Reflection Protocol:
   https://grpc.io/docs/guides/reflection/
"""

from .reflect_client import GrpcReflectClient, GrpcReflectError

__all__ = ["GrpcReflectClient", "GrpcReflectError"]
