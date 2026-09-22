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
"""Live signals (Manager GUI host bus): the hub opens one upstream stream per
owning endpoint, fans out to many clients at <= 10 Hz and closes streams
nobody needs; the bridge's WebSocket and set endpoints on top of it.

The signal cluster is fake but real gRPC: one discovery and two graph
services on local ports, speaking signal.proto."""

import asyncio
import os
import sys
import threading
import time
from concurrent import futures

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

grpc = pytest.importorskip("grpc")

from MicroserviceBase.adapters.signals import (  # noqa: E402
    DISCOVERY_ADDR_ENV,
    HubRegistry,
    SignalError,
    SignalHub,
    check_names,
    parse_addr,
    resolve_discovery,
)
from MicroserviceBase.adapters.signals import signal_proto as sp  # noqa: E402

G1_SIGNALS = ["bench.chamber.temp.degC", "bench.chamber.setpoint.degC", "bench.chamber.humidity.pct"]
G2_SIGNALS = ["bench.psu.voltage.V", "bench.psu.current.A"]
FIVE = G1_SIGNALS + G2_SIGNALS


class FakeGraph:
   """A signal_graph service: Subscribe streams every 10 ms; counts open streams."""

   def __init__(self, names, setpoints=()):
      self.names = set(names)
      self.setpoints = set(setpoints)
      self.values = {n: 0.0 for n in names}
      self.active = 0
      self.opened = 0
      self.requests = []
      self._lock = threading.Lock()

   def subscribe(self, request, context):
      wanted = [n for n in request.signal_names if n in self.names]
      with self._lock:
         self.active += 1
         self.opened += 1
         self.requests.append(sorted(request.signal_names))

      def closed():
         with self._lock:
            self.active -= 1
      context.add_callback(closed)
      Update = sp.message("SignalUpdate")
      i = 0
      while context.is_active():
         for n in wanted:
            self.values[n] += 1
            yield Update(signal_name=n, value=self.values[n], timestamp=time.time())
         i += 1
         time.sleep(0.01)

   def set_signal(self, request, context):
      Resp = sp.message("SetSignalResponse")
      if request.name not in self.setpoints:
         return Resp(success=False, message=f"{request.name} is not a setpoint")
      self.values[request.name] = request.value
      return Resp(success=True, message="ok")


class FakeDiscovery:
   def __init__(self):
      self.catalog = {}          # name -> "host:port"

   def list_signals(self, request, context):
      Meta, Resp = sp.message("SignalMeta"), sp.message("ListSignalsResponse")
      out = []
      for name, ep in sorted(self.catalog.items()):
         host, port = ep.rsplit(":", 1)
         m = Meta(name=name, kind="observed", unit="")
         m.endpoint.host, m.endpoint.port = host, int(port)
         out.append(m)
      return Resp(signals=out)


def _server(handlers):
   server = grpc.server(futures.ThreadPoolExecutor(max_workers=64))
   server.add_generic_rpc_handlers(handlers)
   port = server.add_insecure_port("127.0.0.1:0")
   server.start()
   return server, f"127.0.0.1:{port}"


def _graph_handler(g):
   req, _resp, _ = sp.method_types("SignalQueryService", "Subscribe")
   sreq, sresp, _ = sp.method_types("SignalQueryService", "SetSignal")
   return grpc.method_handlers_generic_handler("signal.SignalQueryService", {
      "Subscribe": grpc.unary_stream_rpc_method_handler(
         g.subscribe, request_deserializer=req.FromString,
         response_serializer=lambda m: m.SerializeToString()),
      "SetSignal": grpc.unary_unary_rpc_method_handler(
         g.set_signal, request_deserializer=sreq.FromString, response_serializer=sresp.SerializeToString),
   })


def _discovery_handler(d):
   req, resp, _ = sp.method_types("SignalDiscoveryService", "ListSignals")
   return grpc.method_handlers_generic_handler("signal.SignalDiscoveryService", {
      "ListSignals": grpc.unary_unary_rpc_method_handler(
         d.list_signals, request_deserializer=req.FromString, response_serializer=resp.SerializeToString),
   })


@pytest.fixture
def cluster():
   g1 = FakeGraph(G1_SIGNALS, setpoints=["bench.chamber.setpoint.degC"])
   g2 = FakeGraph(G2_SIGNALS)
   disc = FakeDiscovery()
   s1, a1 = _server([_graph_handler(g1)])
   s2, a2 = _server([_graph_handler(g2)])
   sd, ad = _server([_discovery_handler(disc)])
   disc.catalog.update({n: a1 for n in G1_SIGNALS})
   disc.catalog.update({n: a2 for n in G2_SIGNALS})
   yield {"g1": g1, "g2": g2, "disc": disc, "a1": a1, "a2": a2, "discovery": ad}
   for s in (s1, s2, sd):
      s.stop(0)


def _wait(pred, timeout=5.0):
   end = time.time() + timeout
   while time.time() < end:
      if pred():
         return True
      time.sleep(0.02)
   return pred()


async def _await(pred, timeout=5.0):
   end = time.monotonic() + timeout
   while time.monotonic() < end:
      if pred():
         return True
      await asyncio.sleep(0.02)
   return pred()


class Test_Names:

   def test_addresses_and_names_are_checked(self):
      assert parse_addr(" 127.0.0.1:50210 ") == "127.0.0.1:50210"
      for bad in ["127.0.0.1", "host:0", "host:70000", "http://h:1", "a b:1"]:
         with pytest.raises(SignalError):
            parse_addr(bad)
      assert check_names(["bench.psu.voltage.V"]) == ["bench.psu.voltage.V"]
      for bad in ["nodot", "a..b", "a.b c", 5, "a.b;drop"]:
         with pytest.raises(SignalError):
            check_names([bad])

   def test_discovery_order(self, monkeypatch):
      monkeypatch.delenv(DISCOVERY_ADDR_ENV, raising=False)
      assert resolve_discovery("h:1", consul="http://c:8500") == "h:1"
      monkeypatch.setenv(DISCOVERY_ADDR_ENV, "env:2")
      assert resolve_discovery(None, consul="http://c:8500") == "env:2"
      monkeypatch.delenv(DISCOVERY_ADDR_ENV)
      with pytest.raises(SignalError, match="No signal-discovery address"):
         resolve_discovery()
      with pytest.raises(SignalError, match="not a Consul HTTP URL"):
         resolve_discovery(consul="file:///etc")


class Test_Hub:

   def test_twenty_tiles_five_signals_two_streams(self, cluster):
      """The M3 acceptance case: 20 subscribers of the same 5 signals open
      one stream per owning endpoint, fed at <= 10 Hz each, and none after
      they leave."""
      async def run():
         hub = SignalHub(cluster["discovery"], flush_interval=0.1)
         received = [[] for _ in range(20)]
         clients = []
         for i in range(20):
            async def send(msg, i=i):
               received[i].append((time.monotonic(), msg))
            c = hub.add_client(send)
            clients.append(c)
            await hub.subscribe(c, FIVE)
         assert await _await(lambda: cluster["g1"].active == 1 and cluster["g2"].active == 1)
         st = hub.stats()
         assert st["upstreams"] == {cluster["a1"]: sorted(G1_SIGNALS), cluster["a2"]: sorted(G2_SIGNALS)}
         assert cluster["g1"].opened == 1 and cluster["g2"].opened == 1
         t0 = time.monotonic()
         await asyncio.sleep(1.0)
         for msgs in received:
            updates = [m for t, m in msgs if m["type"] == "update" and t >= t0]
            assert 5 <= len(updates) <= 11            # ~10 Hz, never more
            names = {v["name"] for m in updates for v in m["values"]}
            assert names == set(FIVE)
         assert hub.stats()["coalesced"] > 0           # the 100 Hz source was thinned out
         for c in clients:
            await hub.remove_client(c)
         assert await _await(lambda: cluster["g1"].active == 0 and cluster["g2"].active == 0)
         assert hub.stats()["upstreams"] == {}
         await hub.close()
      asyncio.run(run())

   def test_a_new_name_restarts_only_its_endpoint(self, cluster):
      async def run():
         hub = SignalHub(cluster["discovery"])
         a = hub.add_client(lambda m: asyncio.sleep(0))
         await hub.subscribe(a, G1_SIGNALS[:1] + G2_SIGNALS[:1])
         assert await _await(lambda: cluster["g1"].active == 1 and cluster["g2"].active == 1)
         b = hub.add_client(lambda m: asyncio.sleep(0))
         await hub.subscribe(b, G1_SIGNALS[1:2])
         assert await _await(lambda: cluster["g1"].opened == 2 and cluster["g1"].active == 1)
         assert cluster["g1"].requests[-1] == sorted(G1_SIGNALS[:2])
         assert cluster["g2"].opened == 1              # untouched
         await hub.unsubscribe(a, G2_SIGNALS[:1])
         assert await _await(lambda: cluster["g2"].active == 0)
         await hub.close()
         assert await _await(lambda: cluster["g1"].active == 0)
      asyncio.run(run())

   def test_unknown_names_are_reported_then_picked_up(self, cluster):
      async def run():
         hub = SignalHub(cluster["discovery"], catalog_ttl=0.3)
         got = []

         async def send(m):
            got.append(m)
         c = hub.add_client(send)
         assert await hub.subscribe(c, ["bench.later.value.x"]) == ["bench.later.value.x"]
         assert any(m["type"] == "unknown" for m in got)
         cluster["g2"].names.add("bench.later.value.x")
         cluster["g2"].values["bench.later.value.x"] = 0.0
         cluster["disc"].catalog["bench.later.value.x"] = cluster["a2"]
         assert await _await(lambda: any(m["type"] == "update" for m in got), timeout=5)
         await hub.close()
      asyncio.run(run())

   def test_set_signal(self, cluster):
      async def run():
         hub = SignalHub(cluster["discovery"])
         assert await hub.set_signal("bench.chamber.setpoint.degC", 60) == (True, "ok")
         ok, msg = await hub.set_signal("bench.chamber.temp.degC", 1)
         assert ok is False and "not a setpoint" in msg
         with pytest.raises(SignalError, match="not in the signal catalog"):
            await hub.set_signal("bench.nope.x.y", 1)
         await hub.close()
      asyncio.run(run())
      assert cluster["g1"].values["bench.chamber.setpoint.degC"] == 60

   def test_discovery_down_is_an_error(self):
      async def run():
         hub = SignalHub("127.0.0.1:1")
         c = hub.add_client(lambda m: asyncio.sleep(0))
         assert await hub.subscribe(c, ["bench.a.b"]) == ["bench.a.b"]
         assert "signal-discovery at 127.0.0.1:1" in hub.stats()["catalog_error"]
         await hub.close()
      asyncio.run(run())


class Test_Bridge:

   @pytest.fixture
   def app(self):
      pytest.importorskip("fastapi")
      pytest.importorskip("httpx")
      from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import FastAPIBridge
      bridge = FastAPIBridge(host="localhost", port=1112, allowed_origins=["http://gui.example"])
      return bridge._build_app() or bridge._app

   def test_stream_fans_out_and_closes(self, app, cluster):
      from fastapi.testclient import TestClient
      with TestClient(app) as client:
         with client.websocket_connect("/api/signals/stream") as a, \
              client.websocket_connect("/api/signals/stream") as b:
            for ws in (a, b):
               ws.send_json({"op": "subscribe", "names": FIVE, "discovery": cluster["discovery"]})
               assert ws.receive_json() == {"type": "ready", "discovery": cluster["discovery"]}
            seen = {"a": set(), "b": set()}
            for key, ws in (("a", a), ("b", b)):
               while seen[key] != set(FIVE):
                  m = ws.receive_json()
                  if m["type"] == "update":
                     seen[key] |= {v["name"] for v in m["values"]}
            stats = client.get("/api/signals/stats").json()["hubs"][0]
            assert stats["clients"] == 2
            assert len(stats["upstreams"]) == 2
            assert cluster["g1"].active == 1 and cluster["g2"].active == 1
            a.send_json({"op": "unsubscribe", "names": G2_SIGNALS})
            b.send_json({"op": "unsubscribe", "names": G2_SIGNALS})
            assert _wait(lambda: cluster["g2"].active == 0)
            a.send_json({"op": "bogus"})
            while True:
               m = a.receive_json()
               if m["type"] == "error":
                  assert "unknown op" in m["message"]
                  break
            b.send_json({"op": "subscribe", "names": ["not a name"]})
            while True:
               m = b.receive_json()
               if m["type"] == "error":
                  assert "not a signal name" in m["message"]
                  break
         assert _wait(lambda: cluster["g1"].active == 0 and cluster["g2"].active == 0)

   def test_set_and_catalog(self, app, cluster):
      from fastapi.testclient import TestClient
      with TestClient(app) as client:
         r = client.post("/api/signals/set", json={"name": "bench.chamber.setpoint.degC", "value": 42,
                                                   "discovery": cluster["discovery"]}).json()
         assert r == {"status": "ok", "success": True, "message": "ok"}
         r = client.post("/api/signals/set", json={"name": "bench.chamber.setpoint.degC", "value": "x",
                                                   "discovery": cluster["discovery"]}).json()
         assert r["status"] == "error"
         r = client.get("/api/signals/catalog", params={"discovery": cluster["discovery"]}).json()
         assert [s["name"] for s in r["signals"]] == sorted(FIVE)

   def test_foreign_origin_is_refused(self, app):
      from fastapi.testclient import TestClient
      from starlette.websockets import WebSocketDisconnect
      with TestClient(app) as client:
         with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/signals/stream", headers={"Origin": "http://evil.example"}) as ws:
               ws.receive_json()
