"""gRPC reflection helper.

Enables the standard gRPC server reflection protocol so clients can list
services and methods at runtime — which is how :mod:`MicroserviceManagerGUI`
discovers the method surface of each registered service without needing to
know each ``.proto`` ahead of time.
"""

from __future__ import annotations

from typing import Iterable

import grpc
from grpc_reflection.v1alpha import reflection


def enable_reflection(server: grpc.aio.Server, service_names: Iterable[str]) -> None:
    """Register the reflection service on *server*.

    Args:
        server:        The running async gRPC server.
        service_names: Fully-qualified service names to advertise, e.g.
                       ``["hello.v1.HelloService", ...]``.  The reflection
                       service itself is added automatically.
    """
    names = tuple(service_names) + (reflection.SERVICE_NAME,)
    reflection.enable_server_reflection(names, server)
