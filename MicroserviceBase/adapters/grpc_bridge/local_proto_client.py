"""Compatibility re-export for `LocalProtoClient`.

QConnectBase (`QConnectBase.grpc.grpc_client`) imports the fallback
client as::

    from MicroserviceBase.adapters.grpc_bridge.local_proto_client import (
        LocalProtoClient,
    )

The class itself lives in :mod:`reflect_client` alongside
:class:`GrpcReflectClient` — they share a lot of internal helpers and
keeping them in one file keeps imports cheap.  This thin module just
re-exports the class under the legacy path so QConnectBase's
``try: import`` succeeds and ``_HAS_LOCAL_PROTO`` flips to True.

If you start a new caller, prefer the canonical import:

    from MicroserviceBase.adapters.grpc_bridge.reflect_client import (
        LocalProtoClient,
    )
"""
from __future__ import annotations

from .reflect_client import LocalProtoClient

__all__ = ["LocalProtoClient"]
