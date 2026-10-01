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
Live-signal endpoints of the UI bridge (the Manager GUI's host bus).

``WS /api/signals/stream``

  Client -> bridge, JSON text frames:

  * ``{"op": "subscribe", "names": [...], "discovery": "host:port"?, "consul": url?}``
    The first subscribe picks signal-discovery (see ``resolve_discovery``).
  * ``{"op": "unsubscribe", "names": [...]}``
  * ``{"op": "stats"}``

  Bridge -> client:

  * ``{"type": "ready", "discovery": "host:port"}``
  * ``{"type": "update", "values": [{"name", "value", "ts"}]}`` (<= 10 Hz,
    latest value per signal)
  * ``{"type": "unknown", "names": [...], "message": ...}`` (retried when
    the catalog refreshes)
  * ``{"type": "status", "endpoint": ..., "state": "subscribed"|"retrying", "message": ...}``
  * ``{"type": "stats", ...}``, ``{"type": "error", "message": ...}``

``POST /api/signals/set``      ``{name, value, discovery?, consul?}``
``GET  /api/signals/catalog``  ``?discovery=&consul=``
``GET  /api/signals/stats``    every hub's open streams
"""

# No `from __future__ import annotations` here: FastAPI resolves the route
# parameter annotations (WebSocket, Any) at registration time.
import asyncio
import logging
from typing import Any, Callable, Optional

from ..signals import HubRegistry, SignalError, resolve_discovery

logger = logging.getLogger(__name__)


def register_routes(app, origin_allowed: Callable[[Any, str], bool], registry: Optional[HubRegistry] = None):
   """
Add the live-signal endpoints to the bridge app.

**Arguments:**

* ``app``

  / *Condition*: required / *Type*: FastAPI /

* ``origin_allowed``

  / *Condition*: required / *Type*: callable /

  ``(websocket, what) -> bool``; the HTTP origin middleware does not see
  WebSocket handshakes.

* ``registry``

  / *Condition*: optional / *Type*: HubRegistry /

  Hubs per discovery address; tests pass one with their own channels.

**Returns:**

* ``registry``

  / *Type*: HubRegistry /
   """
   from fastapi import Body, WebSocket, WebSocketDisconnect

   registry = registry or HubRegistry()

   async def _discovery(discovery, consul):
      # The Consul lookup is blocking HTTP; keep it off the event loop.
      return await asyncio.to_thread(resolve_discovery, discovery or None, consul or None)

   @app.websocket("/api/signals/stream")
   async def signals_stream(websocket: WebSocket):
      if not origin_allowed(websocket, "WebSocket /api/signals/stream"):
         await websocket.close(code=1008)
         return
      await websocket.accept()
      lock = asyncio.Lock()

      async def send(msg):
         async with lock:
            await websocket.send_json(msg)

      hub = client = None
      try:
         while True:
            try:
               msg = await websocket.receive_json()
            except ValueError:
               await send({"type": "error", "message": "frames are JSON objects"})
               continue
            op = msg.get("op") if isinstance(msg, dict) else None
            try:
               if op == "subscribe":
                  if hub is None:
                     addr = await _discovery(msg.get("discovery"), msg.get("consul"))
                     hub = registry.get(addr)
                     client = hub.add_client(send)
                     await send({"type": "ready", "discovery": hub.discovery})
                  await hub.subscribe(client, msg.get("names") or [])
               elif op == "unsubscribe":
                  if hub is not None:
                     await hub.unsubscribe(client, msg.get("names") or [])
               elif op == "stats":
                  await send(dict(hub.stats() if hub else {}, type="stats"))
               else:
                  await send({"type": "error", "message": f"unknown op {op!r}"})
            except SignalError as exc:
               await send({"type": "error", "message": str(exc)})
      except WebSocketDisconnect:
         pass
      finally:
         if hub is not None and client is not None:
            await hub.remove_client(client)

   @app.post("/api/signals/set")
   async def signals_set(body: Any = Body(...)):
      if not isinstance(body, dict) or "name" not in body or "value" not in body:
         return {"status": "error", "error": "send {name, value}"}
      try:
         value = float(body["value"])
         hub = registry.get(await _discovery(body.get("discovery"), body.get("consul")))
         ok, message = await hub.set_signal(body["name"], value)
      except (SignalError, TypeError, ValueError) as exc:
         return {"status": "error", "error": str(exc)}
      return {"status": "ok", "success": ok, "message": message}

   @app.get("/api/signals/catalog")
   async def signals_catalog(discovery: str = "", consul: str = ""):
      try:
         hub = registry.get(await _discovery(discovery, consul))
         cat = await hub.catalog(refresh=True)
      except SignalError as exc:
         return {"status": "error", "error": str(exc)}
      return {"status": "ok", "discovery": hub.discovery, "signals": sorted(cat.values(), key=lambda s: s["name"])}

   @app.get("/api/signals/stats")
   async def signals_stats():
      return {"status": "ok", "hubs": [h.stats() for h in registry.all()]}

   return registry
