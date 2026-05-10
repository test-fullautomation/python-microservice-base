"""
Consul service registration and lookup.

Direct HTTP client (no python-consul dependency).  Consul's HTTP API is
small and stable; adding a third-party wrapper adds a dependency without
value.

The :class:`ConsulRegistration` class is used as an async context
manager::

    async with ConsulRegistration(
        name="hello",
        address="127.0.0.1",
        port=50051,
        consul_addr="http://localhost:8500",
    ):
        await server.wait_for_termination()

The service is registered when the context is entered and deregistered
on exit.  A gRPC health check is registered against the same port so
Consul can mark the service healthy / unhealthy automatically.

For client-side lookup, :func:`resolve_via_consul` returns the first
healthy ``host:port`` registered under a service name.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional, Sequence

import httpx

logger = logging.getLogger(__name__)


class ConsulRegistration:
    """
Async context manager that registers a service with Consul on entry
and deregisters it on exit.

The service ID is generated from the service name and a short random
suffix so multiple instances of the same service can coexist on the
same node.
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
        """
Construct a ConsulRegistration context manager.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Logical service name, e.g. ``"hello"``.

* ``address``

  / *Condition*: required / *Type*: str /

  Address other services should use to reach this one.

* ``port``

  / *Condition*: required / *Type*: int /

  gRPC port.

* ``consul_addr``

  / *Condition*: optional / *Type*: str / *Default*: "http://localhost:8500" /

  Consul HTTP API endpoint.

* ``tags``

  / *Condition*: optional / *Type*: Sequence[str] / *Default*: None /

  Optional Consul tags (e.g. ``["v1", "demo"]``).

* ``meta``

  / *Condition*: optional / *Type*: dict[str, str] / *Default*: None /

  Optional key/value metadata attached to the service.

* ``token``

  / *Condition*: optional / *Type*: str / *Default*: "" /

  Optional Consul ACL token.

* ``health_interval``

  / *Condition*: optional / *Type*: str / *Default*: "10s" /

  How often Consul probes the gRPC health endpoint.

* ``health_timeout``

  / *Condition*: optional / *Type*: str / *Default*: "2s" /

  Health probe timeout.

* ``deregister_after``

  / *Condition*: optional / *Type*: str / *Default*: "1m" /

  Deregister the service if it stays critical for this long.
        """
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
        """
The randomly-suffixed service ID this registration uses.

**Returns:**

* ``service_id``

  / *Type*: str /

  Concatenation of service name and a short hex suffix.
        """
        return self._service_id

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ConsulRegistration":
        """
Open the HTTP client and register the service with Consul.

**Returns:**

* ``self``

  / *Type*: ConsulRegistration /

  The instance, so callers can grab ``service_id`` from inside the
  ``async with`` block.
        """
        headers = {"X-Consul-Token": self._token} if self._token else {}
        self._client = httpx.AsyncClient(
            base_url=self._consul_addr,
            headers=headers,
            timeout=5.0,
        )
        await self._register()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """
Deregister the service and close the HTTP client.

**Returns:**

(*no returns*)
        """
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
        """
PUT the service definition to Consul.

**Returns:**

(*no returns*)
        """
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
        """
PUT the deregister request.  Logs and swallows any failure so the
context manager still closes cleanly.

**Returns:**

(*no returns*)
        """
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


# ----------------------------------------------------------------------
# Client-side lookup
# ----------------------------------------------------------------------

def resolve_via_consul(consul_addr: str, service_name: str,
                       timeout: float = 5.0) -> str:
   """
Resolve a Consul service name to a ``host:port`` string.

Calls ``GET /v1/health/service/<name>?passing=true`` and returns the
first healthy instance.  Synchronous (uses ``httpx.Client``) — designed
for client-side bootstrap of a single channel, not for hot paths.

For per-call resolution, prefer the gRPC channel's built-in
``consul://`` resolver in MicroserviceBase's C++ ``ServiceClient<T>``,
or use the bridge's ``/api/consul/health/<svc>`` endpoint.

**Arguments:**

* ``consul_addr``

  / *Condition*: required / *Type*: str /

  Consul HTTP API endpoint, e.g. ``"http://localhost:8500"``.

* ``service_name``

  / *Condition*: required / *Type*: str /

  Logical service name as registered with Consul.

* ``timeout``

  / *Condition*: optional / *Type*: float / *Default*: 5.0 /

  HTTP request timeout in seconds.

**Returns:**

* ``endpoint``

  / *Type*: str /

  ``host:port`` string of the first healthy instance.  Empty string
  when no healthy instance is registered.

**Raises:**

* ``httpx.HTTPError``

  When the Consul API call itself fails (network error, 5xx, etc.).
   """
   base = consul_addr.rstrip("/")
   url = f"{base}/v1/health/service/{service_name}"
   with httpx.Client(timeout=timeout) as client:
      resp = client.get(url, params={"passing": "true"})
      resp.raise_for_status()
      entries = resp.json()
   if not entries:
      return ""

   # Each entry has Service.Address, Service.Port, Node.Address.  Service
   # address may be empty — fall back to the node's address in that case.
   first = entries[0]
   service = first.get("Service") or {}
   node    = first.get("Node") or {}
   address = service.get("Address") or node.get("Address") or ""
   port    = service.get("Port") or 0
   if not address or not port:
      return ""
   return f"{address}:{port}"
