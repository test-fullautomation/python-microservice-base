"""Consul service registration.

Direct HTTP client (no python-consul dependency).  Consul's HTTP API is small
and stable; adding a third-party wrapper adds a dependency without value.

The :class:`ConsulRegistration` class is used as an async context manager:

.. code-block:: python

    async with ConsulRegistration(
        name="hello",
        address="127.0.0.1",
        port=50051,
        consul_addr="http://localhost:8500",
    ):
        await server.wait_for_termination()

The service is registered when the context is entered and deregistered on
exit.  A gRPC health check is registered against the same port so Consul
can mark the service healthy/unhealthy automatically.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional, Sequence

import httpx

logger = logging.getLogger(__name__)


class ConsulRegistration:
    """Async context manager that registers a service with Consul on entry
    and deregisters it on exit.

    The service ID is generated from the service name and a short random
    suffix so multiple instances of the same service can coexist on the
    same node.

    Args:
        name:          Logical service name, e.g. ``"hello"``.
        address:       Address other services should use to reach this one.
        port:          gRPC port.
        consul_addr:   Consul HTTP API endpoint.
        tags:          Optional Consul tags (e.g. ``["v1", "demo"]``).
        meta:          Optional key/value metadata attached to the service.
        token:         Optional Consul ACL token.
        health_interval: How often Consul probes the gRPC health endpoint.
        health_timeout:  Health probe timeout.
        deregister_after: Deregister the service if critical for this long.
    """

    def __init__(
        self,
        name: str,
        address: str,
        port: int,
        consul_addr: str = "http://localhost:8500",
        tags: Optional[Sequence[str]] = None,
        meta: Optional[dict[str, str]] = None,
        token: str = "",
        health_interval: str = "10s",
        health_timeout: str = "2s",
        deregister_after: str = "1m",
    ) -> None:
        self._name = name
        self._address = address
        self._port = port
        self._consul_addr = consul_addr.rstrip("/")
        self._tags = list(tags or [])
        self._meta = dict(meta or {})
        self._token = token
        self._health_interval = health_interval
        self._health_timeout = health_timeout
        self._deregister_after = deregister_after

        # Unique ID so multiple instances of the same service can coexist.
        self._service_id = f"{name}-{uuid.uuid4().hex[:8]}"
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def service_id(self) -> str:
        return self._service_id

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ConsulRegistration":
        headers = {"X-Consul-Token": self._token} if self._token else {}
        self._client = httpx.AsyncClient(
            base_url=self._consul_addr,
            headers=headers,
            timeout=5.0,
        )
        await self._register()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            await self._deregister()
        finally:
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _register(self) -> None:
        assert self._client is not None
        payload = {
            "ID": self._service_id,
            "Name": self._name,
            "Address": self._address,
            "Port": self._port,
            "Tags": self._tags,
            "Meta": self._meta,
            "Check": {
                # gRPC health check against the standard grpc.health.v1 protocol.
                "GRPC": f"{self._address}:{self._port}",
                "GRPCUseTLS": False,
                "Interval": self._health_interval,
                "Timeout": self._health_timeout,
                "DeregisterCriticalServiceAfter": self._deregister_after,
            },
        }
        logger.info(
            "Registering service %s (id=%s) with Consul at %s:%d",
            self._name, self._service_id, self._address, self._port,
        )
        resp = await self._client.put("/v1/agent/service/register", json=payload)
        resp.raise_for_status()

    async def _deregister(self) -> None:
        if self._client is None:
            return
        logger.info("Deregistering service %s (id=%s)", self._name, self._service_id)
        try:
            resp = await self._client.put(
                f"/v1/agent/service/deregister/{self._service_id}"
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to deregister %s: %s", self._service_id, exc)
