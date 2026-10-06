"""
Tests for finding local Nomad and Consul agents
(``/api/nomad/discover``, ``/api/consul/discover`` in
adapters/ui_bridge/fastapi_bridge.py).

The processes are psutil stand-ins whose listening ports are a real local
HTTP server, so the probe itself is real. Covered: an agent is found with
psutil 5's ``connections()`` and with a proxy in the environment that would
swallow 127.0.0.1; a process whose ports cannot be read, and one whose port
answers 403, are reported under ``skipped`` with the reason.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
psutil = pytest.importorskip("psutil")
from fastapi.testclient import TestClient  # noqa: E402

from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import FastAPIBridge  # noqa: E402

AGENT_SELF = {"member": {"Name": "demo-server"},
              "config": {"Version": "1.9.0", "Datacenter": "dc1", "Server": {"Enabled": True}}}


class _Agent(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):   # noqa: N802 - http.server's name
        if self.status != 200:
            self.send_error(self.status)
            return
        path = self.path.split("?", 1)[0]   # NomadClient adds ?namespace=
        body = json.dumps(AGENT_SELF if path == "/v1/agent/self" else "127.0.0.1:8300").encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve(status):
    handler = type("Agent%d" % status, (_Agent,), {"status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _listen(port):
    return SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(ip="127.0.0.1", port=port))


class _OldPsutilProc:
    """A process as psutil 5 shows it: ``connections`` only."""

    def __init__(self, pid, name, ports):
        self.pid, self.info, self._ports = pid, {"pid": pid, "name": name, "exe": ""}, ports

    def connections(self, kind="tcp"):
        return [_listen(p) for p in self._ports]


class _OtherUsersProc:
    def __init__(self, pid, name):
        self.pid, self.info = pid, {"pid": pid, "name": name, "exe": ""}

    def net_connections(self, kind="tcp"):
        raise psutil.AccessDenied(self.pid)


@pytest.fixture
def agents(monkeypatch):
    ok, denied = _serve(200), _serve(403)
    # A proxy that is not there, and 127.0.0.1 not exempted from it.
    for name in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "")
    yield ok.server_address[1], denied.server_address[1]
    ok.shutdown()
    denied.shutdown()


def _client():
    bridge = FastAPIBridge(host="localhost", port=1112)
    return TestClient(bridge._build_app() or bridge._app)


@pytest.mark.parametrize("agent, path", [("nomad", "/api/nomad/discover"), ("consul", "/api/consul/discover")])
def test_found_with_old_psutil_and_a_proxy_and_the_rest_explained(monkeypatch, agents, agent, path):
    ok_port, denied_port = agents
    procs = [
        _OldPsutilProc(101, agent + ".exe", [ok_port]),
        _OtherUsersProc(102, agent),
        _OldPsutilProc(103, agent, [denied_port]),
        _OldPsutilProc(104, "nomad-helper", [ok_port]),   # not the agent's binary
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(procs))

    data = _client().get(path).json()

    assert [(i["pid"], i["port"]) for i in data["instances"]] == [(101, ok_port)]
    if agent == "nomad":
        assert data["instances"][0]["name"] == "demo-server" and data["instances"][0]["server"] is True
    else:
        assert data["instances"][0]["leader"] == "127.0.0.1:8300"
    reasons = {s["pid"]: s["reason"] for s in data["skipped"]}
    assert set(reasons) == {102, 103}
    assert "cannot be read" in reasons[102]
    assert "HTTP 403" in reasons[103] and str(denied_port) in reasons[103]


def test_a_local_agent_is_reached_past_the_proxy(monkeypatch, agents):
    """Once connected, Nomad (NomadClient) and Consul (the bridge's calls) on
    127.0.0.1 are reached directly too; a remote address keeps the proxy."""
    ok_port, _ = agents
    monkeypatch.setenv("NOMAD_ADDR", "http://127.0.0.1:%d" % ok_port)
    client = _client()
    nomad = client.get("/api/nomad/health").json()
    assert nomad["ok"] is True and nomad["server"] == "demo-server", nomad
    consul = client.get("/api/consul/health", params={"consul": "http://127.0.0.1:%d" % ok_port}).json()
    assert consul["ok"] is True and consul["leader"] == "127.0.0.1:8300", consul

    from MicroserviceBase.adapters.nomad_hub.nomad_client import is_loopback_url
    assert is_loopback_url("http://localhost:4646") and is_loopback_url("http://[::1]:4646")
    assert not is_loopback_url("http://nomad.example.com:4646")
