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
"""
Live signals for the Manager GUI: one upstream stream per owning service,
fanned out to every GUI client that wants its signals.

``signal-discovery`` says which ``signal_graph`` service owns each signal
(``SignalMeta.endpoint``); the data never passes through discovery. The
hub keeps **one** ``SignalQueryService/Subscribe`` stream per owning
endpoint, subscribed to the union of the names its clients want, and
restarts it when that union changes (the RPC has no add/remove). With no
client left for an endpoint, its stream is cancelled.

Each client receives the **latest** value per signal at most every
``flush_interval`` seconds (default 0.1 s, i.e. <= 10 Hz): a fast signal
never queues up behind a slow browser.

Names discovery does not know are reported to the client and retried when
the catalog refreshes, so a tile opened before its graph service started
fills in once the service is up.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set, Tuple

from . import signal_proto as sp

logger = logging.getLogger(__name__)

DISCOVERY_ADDR_ENV = "MB_SIGNAL_DISCOVERY_ADDR"
DISCOVERY_SERVICE_ENV = "MB_SIGNAL_DISCOVERY_SERVICE"
DEFAULT_DISCOVERY_SERVICE = "signal-discovery"

_ADDR_RE = re.compile(r"^(?P<host>[A-Za-z0-9._-]+|\[[0-9A-Fa-f:]+\]):(?P<port>\d{1,5})$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)+$")


class SignalError(RuntimeError):
   """A discovery address, a signal name or an upstream call the hub cannot use."""


def parse_addr(addr: str) -> str:
   """
Normalise ``host:port``.

**Raises:**

* ``SignalError`` when *addr* is not ``host:port`` with a port 1-65535.
   """
   m = _ADDR_RE.match(str(addr or "").strip())
   if not m or not 0 < int(m.group("port")) < 65536:
      raise SignalError(f"{addr!r} is not host:port")
   return f"{m.group('host')}:{int(m.group('port'))}"


def check_names(names: Iterable[Any]) -> List[str]:
   """
Signal names as the GUI may send them: dotted, e.g. ``bench.psu.voltage.V``.

**Raises:**

* ``SignalError`` for anything else (keeps odd strings off the upstream).
   """
   out = []
   for n in names or []:
      if not isinstance(n, str) or not _NAME_RE.match(n) or len(n) > 200:
         raise SignalError(f"{n!r} is not a signal name (dotted, e.g. bench.psu.voltage.V)")
      out.append(n)
   return out


def resolve_discovery(discovery: Optional[str] = None, consul: Optional[str] = None,
                      service: Optional[str] = None, timeout: float = 4.0) -> str:
   """
Where ``signal-discovery`` answers, in this order: an explicit address,
``MB_SIGNAL_DISCOVERY_ADDR``, then the first passing instance of the
discovery service (``MB_SIGNAL_DISCOVERY_SERVICE``, default
``signal-discovery``) in the given Consul.

**Arguments:**

* ``discovery``

  / *Condition*: optional / *Type*: str /

  ``host:port`` set by the user.

* ``consul``

  / *Condition*: optional / *Type*: str /

  Consul HTTP URL the GUI is connected to.

**Returns:**

* ``addr``

  / *Type*: str /

  ``host:port`` of signal-discovery.

**Raises:**

* ``SignalError`` when none of them gives an address.
   """
   if discovery:
      return parse_addr(discovery)
   env = os.environ.get(DISCOVERY_ADDR_ENV, "").strip()
   if env:
      return parse_addr(env)
   name = service or os.environ.get(DISCOVERY_SERVICE_ENV, "").strip() or DEFAULT_DISCOVERY_SERVICE
   if consul:
      u = urllib.parse.urlparse(consul)
      if u.scheme not in ("http", "https") or not u.netloc:
         raise SignalError(f"{consul!r} is not a Consul HTTP URL")
      url = f"{consul.rstrip('/')}/v1/health/service/{urllib.parse.quote(name)}?passing=true"
      try:
         with urllib.request.urlopen(url, timeout=timeout) as resp:
            entries = json.loads(resp.read().decode("utf-8") or "[]")
      except Exception as exc:  # noqa: BLE001 - reported to the GUI as is
         raise SignalError(f"Consul {consul} did not answer: {exc}") from exc
      for e in entries:
         svc = e.get("Service") or {}
         host = svc.get("Address") or (e.get("Node") or {}).get("Address")
         if host and svc.get("Port"):
            return parse_addr(f"{host}:{svc['Port']}")
      raise SignalError(f"{name} is not registered (passing) in Consul {consul}; "
                        f"set the discovery address or {DISCOVERY_ADDR_ENV}")
   raise SignalError(f"No signal-discovery address: connect to a Consul that has {name}, "
                     f"or set the discovery address or {DISCOVERY_ADDR_ENV}")


class SignalClient:
   """
One GUI connection: the names it wants and its pending latest values.

``send`` is an async callable taking one JSON-able dict.
   """

   def __init__(self, hub: "SignalHub", send: Callable[[dict], Awaitable[None]], flush_interval: float):
      self.hub = hub
      self.names: Set[str] = set()
      self.unknown: Set[str] = set()
      self._send = send
      self._pending: Dict[str, Tuple[float, float]] = {}
      self._interval = flush_interval
      self._flusher: Optional[asyncio.Task] = None
      self.coalesced = 0

   def offer(self, name: str, value: float, ts: float) -> None:
      if name in self._pending:
         self.coalesced += 1          # latest wins
      self._pending[name] = (value, ts)
      if self._flusher is None or self._flusher.done():
         self._flusher = asyncio.ensure_future(self._flush_later())

   async def _flush_later(self) -> None:
      await asyncio.sleep(self._interval)
      batch, self._pending = self._pending, {}
      if batch:
         await self.send({"type": "update", "values": [
            {"name": n, "value": v, "ts": t} for n, (v, t) in sorted(batch.items())]})

   async def send(self, msg: dict) -> None:
      try:
         await self._send(msg)
      except Exception:  # noqa: BLE001 - a closed socket ends the client elsewhere
         pass

   def close(self) -> None:
      if self._flusher and not self._flusher.done():
         self._flusher.cancel()
      self._pending.clear()


class _Upstream:
   """The one Subscribe stream to one owning endpoint."""

   def __init__(self, hub: "SignalHub", endpoint: str):
      self.hub = hub
      self.endpoint = endpoint
      self.names: frozenset = frozenset()
      self.state = "idle"
      self.task: Optional[asyncio.Task] = None

   def restart(self, names: frozenset) -> None:
      self.stop()
      self.names = names
      self.task = asyncio.ensure_future(self._run(names))

   def stop(self) -> None:
      if self.task and not self.task.done():
         self.task.cancel()
      self.task = None

   async def _run(self, names: frozenset) -> None:
      req_cls, resp_cls, _ = sp.method_types("SignalQueryService", "Subscribe")
      backoff = 1.0
      while True:
         call = None
         try:
            channel = self.hub._channel(self.endpoint)
            stream = channel.unary_stream(sp.method_path("SignalQueryService", "Subscribe"),
                                          request_serializer=req_cls.SerializeToString,
                                          response_deserializer=resp_cls.FromString)
            call = stream(req_cls(signal_names=sorted(names)))
            self.hub.streams_opened += 1
            self.state = "subscribed"
            await self.hub._status(self.endpoint, "subscribed", "")
            async for upd in call:
               backoff = 1.0
               self.hub._dispatch(upd.signal_name, upd.value, upd.timestamp)
            message = "stream ended"
         except asyncio.CancelledError:
            if call is not None:
               call.cancel()
            raise
         except Exception as exc:  # noqa: BLE001 - grpc.aio.AioRpcError and friends
            message = getattr(exc, "details", lambda: str(exc))() or str(exc)
         self.state = "retrying"
         await self.hub._status(self.endpoint, "retrying", message)
         # The owner may have moved or restarted: re-read the catalog.
         self.hub._catalog_at = 0.0
         asyncio.ensure_future(self.hub.reconcile(refresh=True))
         await asyncio.sleep(backoff)
         backoff = min(backoff * 2, 10.0)


class SignalHub:
   """
Streams from the ``signal_graph`` services one discovery knows about.

**Arguments:**

* ``discovery``

  / *Condition*: required / *Type*: str /

  ``host:port`` of signal-discovery.

* ``channel_factory``

  / *Condition*: optional / *Type*: callable /

  ``addr -> grpc.aio.Channel``; tests pass their own.

* ``catalog_ttl``, ``flush_interval``

  / *Condition*: optional / *Type*: float /

  Seconds before the catalog is re-read, and between two updates sent to
  one client.
   """

   def __init__(self, discovery: str, channel_factory=None, catalog_ttl: float = 15.0,
                flush_interval: float = 0.1):
      import grpc  # noqa: F401 - fail here, not in a stream, when grpc is missing
      self.discovery = parse_addr(discovery)
      self.loop = asyncio.get_running_loop()
      self._channel_factory = channel_factory or (lambda addr: __import__("grpc").aio.insecure_channel(addr))
      self._channels: Dict[str, Any] = {}
      self._catalog: Dict[str, dict] = {}
      self._catalog_at = 0.0
      self._catalog_error = ""
      self._catalog_lock = asyncio.Lock()
      self._reconcile_lock = asyncio.Lock()
      self._ttl = catalog_ttl
      self._flush_interval = flush_interval
      self.clients: Set[SignalClient] = set()
      self.upstreams: Dict[str, _Upstream] = {}
      self.streams_opened = 0
      self._retry: Optional[asyncio.Task] = None

   # ---- catalog -------------------------------------------------------

   def _channel(self, addr: str):
      ch = self._channels.get(addr)
      if ch is None:
         ch = self._channels[addr] = self._channel_factory(addr)
      return ch

   async def catalog(self, refresh: bool = False) -> Dict[str, dict]:
      """
Signal name -> ``{"name", "kind", "unit", "endpoint"}`` from discovery,
cached for ``catalog_ttl`` seconds.

**Raises:**

* ``SignalError`` when discovery does not answer and nothing is cached.
      """
      async with self._catalog_lock:
         if not refresh and self._catalog and time.monotonic() - self._catalog_at < self._ttl:
            return self._catalog
         req_cls, resp_cls, _ = sp.method_types("SignalDiscoveryService", "ListSignals")
         call = self._channel(self.discovery).unary_unary(
            sp.method_path("SignalDiscoveryService", "ListSignals"),
            request_serializer=req_cls.SerializeToString, response_deserializer=resp_cls.FromString)
         try:
            resp = await call(req_cls(), timeout=5.0)
         except Exception as exc:  # noqa: BLE001
            detail = getattr(exc, "details", lambda: str(exc))() or str(exc)
            self._catalog_error = f"signal-discovery at {self.discovery}: {detail}"
            if self._catalog:
               return self._catalog      # keep serving the last good catalog
            raise SignalError(self._catalog_error) from exc
         cat = {}
         for s in resp.signals:
            if s.endpoint.host and s.endpoint.port:
               cat[s.name] = {"name": s.name, "kind": s.kind, "unit": s.unit,
                              "endpoint": f"{s.endpoint.host}:{s.endpoint.port}"}
         self._catalog, self._catalog_at, self._catalog_error = cat, time.monotonic(), ""
         return cat

   # ---- clients -------------------------------------------------------

   def add_client(self, send: Callable[[dict], Awaitable[None]]) -> SignalClient:
      c = SignalClient(self, send, self._flush_interval)
      self.clients.add(c)
      return c

   async def remove_client(self, client: SignalClient) -> None:
      client.close()
      self.clients.discard(client)
      await self.reconcile()

   async def subscribe(self, client: SignalClient, names: Iterable[str]) -> List[str]:
      """Add names to a client. Returns the names discovery does not know (yet)."""
      names = check_names(names)
      client.names.update(names)
      await self.reconcile()
      unknown = sorted(n for n in names if n in client.unknown)
      if unknown:
         await client.send({"type": "unknown", "names": unknown,
                            "message": self._catalog_error or "not in the signal catalog"})
      return unknown

   async def unsubscribe(self, client: SignalClient, names: Iterable[str]) -> None:
      for n in check_names(names):
         client.names.discard(n)
         client.unknown.discard(n)
      await self.reconcile()

   # ---- streams -------------------------------------------------------

   async def reconcile(self, refresh: bool = False) -> None:
      """Make the upstream streams match what the clients want now."""
      async with self._reconcile_lock:
         wanted = set()
         for c in self.clients:
            wanted |= c.names
         try:
            cat = await self.catalog(refresh=refresh) if wanted else self._catalog
         except SignalError:
            cat = {}
         by_ep: Dict[str, Set[str]] = {}
         for c in self.clients:
            c.unknown = {n for n in c.names if n not in cat}
         for n in wanted:
            meta = cat.get(n)
            if meta:
               by_ep.setdefault(meta["endpoint"], set()).add(n)
         for ep in list(self.upstreams):
            if ep not in by_ep:
               self.upstreams.pop(ep).stop()
         for ep, names in by_ep.items():
            up = self.upstreams.get(ep)
            if up is None:
               up = self.upstreams[ep] = _Upstream(self, ep)
            if up.names != frozenset(names) or up.task is None:
               up.restart(frozenset(names))
         self._schedule_retry()

   def _schedule_retry(self) -> None:
      pending = any(c.unknown for c in self.clients)
      if pending and (self._retry is None or self._retry.done()):
         self._retry = asyncio.ensure_future(self._retry_unknown())

   async def _retry_unknown(self) -> None:
      await asyncio.sleep(self._ttl)
      if any(c.unknown for c in self.clients):
         await self.reconcile(refresh=True)

   def _dispatch(self, name: str, value: float, ts: float) -> None:
      for c in self.clients:
         if name in c.names:
            c.offer(name, value, ts)

   async def _status(self, endpoint: str, state: str, message: str) -> None:
      names = self.upstreams.get(endpoint).names if endpoint in self.upstreams else frozenset()
      for c in list(self.clients):
         if c.names & names:
            await c.send({"type": "status", "endpoint": endpoint, "state": state, "message": message})

   # ---- setpoints ------------------------------------------------------

   async def set_signal(self, name: str, value: float) -> Tuple[bool, str]:
      """
Write a setpoint on the service that owns *name*.

**Returns:**

* ``(success, message)``

  / *Type*: tuple /

  As the owner answered; ``success`` is False for observed signals.

**Raises:**

* ``SignalError`` when the name is unknown or the owner does not answer.
      """
      (name,) = check_names([name])
      meta = (await self.catalog()).get(name) or (await self.catalog(refresh=True)).get(name)
      if not meta:
         raise SignalError(f"{name} is not in the signal catalog of {self.discovery}")
      req_cls, resp_cls, _ = sp.method_types("SignalQueryService", "SetSignal")
      call = self._channel(meta["endpoint"]).unary_unary(
         sp.method_path("SignalQueryService", "SetSignal"),
         request_serializer=req_cls.SerializeToString, response_deserializer=resp_cls.FromString)
      try:
         resp = await call(req_cls(name=name, value=float(value)), timeout=5.0)
      except Exception as exc:  # noqa: BLE001
         raise SignalError(f"SetSignal on {meta['endpoint']}: "
                           f"{getattr(exc, 'details', lambda: str(exc))() or exc}") from exc
      return bool(resp.success), resp.message

   # ---- introspection / shutdown -----------------------------------------

   def stats(self) -> dict:
      """What is open right now (tests, the GUI's status strip)."""
      return {
         "discovery": self.discovery,
         "clients": len(self.clients),
         "upstreams": {ep: sorted(up.names) for ep, up in self.upstreams.items()},
         "states": {ep: up.state for ep, up in self.upstreams.items()},
         "streams_opened": self.streams_opened,
         "coalesced": sum(c.coalesced for c in self.clients),
         "catalog_size": len(self._catalog),
         "catalog_error": self._catalog_error,
      }

   async def close(self) -> None:
      for c in list(self.clients):
         c.close()
      self.clients.clear()
      for up in self.upstreams.values():
         up.stop()
      self.upstreams.clear()
      if self._retry and not self._retry.done():
         self._retry.cancel()
      for ch in self._channels.values():
         try:
            await ch.close()
         except Exception:  # noqa: BLE001
            pass
      self._channels.clear()


class HubRegistry:
   """
One hub per discovery address, bound to the event loop that created it (a
hub from a loop that is gone is replaced, not reused).
   """

   def __init__(self, **hub_kwargs):
      self._hubs: Dict[str, SignalHub] = {}
      self._kwargs = hub_kwargs

   def get(self, discovery: str) -> SignalHub:
      addr = parse_addr(discovery)
      loop = asyncio.get_running_loop()
      hub = self._hubs.get(addr)
      if hub is None or hub.loop is not loop or hub.loop.is_closed():
         hub = self._hubs[addr] = SignalHub(addr, **self._kwargs)
      return hub

   def all(self) -> List[SignalHub]:
      return list(self._hubs.values())
