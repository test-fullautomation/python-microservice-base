"""
Tests for the UI bridge origin allow-list (adapters/ui_bridge/fastapi_bridge.py).

Covers acceptance of configured origins, rejection (with a log entry) of
everything else, pass-through of non-browser requests that carry no Origin
header, the ``*`` opt-out, the built-in defaults, env-var configuration,
and the error messages for invalid configuration.
"""

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import (  # noqa: E402
    ALLOWED_ORIGINS_ENV,
    FILE_ORIGIN,
    NULL_ORIGIN,
    FastAPIBridge,
    default_allowed_origins,
    parse_allowed_origins,
)

# A GET route that needs no broker, registry or request handler.
PROBE = "/api/version"

GUI = "http://gui.example:1112"
OTHER = "http://other.example"


def _client(**kwargs):
    host = kwargs.pop("host", "localhost")
    port = kwargs.pop("port", 1112)
    bridge = FastAPIBridge(host=host, port=port, **kwargs)
    app = bridge._build_app() or bridge._app
    return TestClient(app), bridge


class Test_OriginAllowList:

    def test_listed_origin_is_accepted_with_cors_header(self):
        client, _ = _client(allowed_origins=[GUI])
        r = client.get(PROBE, headers={"Origin": GUI})
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == GUI

    def test_unlisted_origin_is_rejected_and_logged(self, caplog):
        client, _ = _client(allowed_origins=[GUI])
        with caplog.at_level(logging.WARNING):
            r = client.get(PROBE, headers={"Origin": OTHER})
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "origin_not_allowed"
        assert body["origin"] == OTHER
        assert ALLOWED_ORIGINS_ENV in body["detail"]
        assert "access-control-allow-origin" not in r.headers
        messages = [rec.getMessage() for rec in caplog.records]
        assert any(OTHER in m and ALLOWED_ORIGINS_ENV in m for m in messages), messages

    def test_preflight_from_unlisted_origin_is_rejected(self):
        client, _ = _client(allowed_origins=[GUI])
        r = client.options(PROBE, headers={"Origin": OTHER,
                                           "Access-Control-Request-Method": "GET"})
        assert r.status_code == 403

    def test_request_without_origin_header_passes(self):
        # curl / Python clients send no Origin. An origin check is not
        # authentication and must not lock them out.
        client, _ = _client(allowed_origins=[GUI])
        assert client.get(PROBE).status_code == 200

    def test_wildcard_disables_the_check(self):
        client, _ = _client(allowed_origins="*")
        r = client.get(PROBE, headers={"Origin": OTHER})
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "*"

    def test_websocket_from_unlisted_origin_is_refused(self, caplog):
        client, _ = _client(allowed_origins=[GUI])
        with caplog.at_level(logging.WARNING):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/ws/updates", headers={"Origin": OTHER}):
                    pass
        assert any("WebSocket" in rec.getMessage() and OTHER in rec.getMessage()
                   for rec in caplog.records)

    def test_websocket_from_listed_origin_connects(self):
        client, _ = _client(allowed_origins=[GUI])
        with client.websocket_connect("/ws/updates", headers={"Origin": GUI}):
            pass


class Test_Defaults:

    def test_loopback_default_admits_local_http_and_electron(self):
        origins = default_allowed_origins("localhost", 1112)
        assert "http://localhost:1112" in origins
        assert "http://127.0.0.1:1112" in origins
        assert NULL_ORIGIN in origins  # Electron loads from file://
        assert FILE_ORIGIN in origins  # ... and its WebSockets say so

    def test_electron_null_origin_accepted_on_loopback_bind(self):
        client, _ = _client(host="localhost", port=1112)
        assert client.get(PROBE, headers={"Origin": NULL_ORIGIN}).status_code == 200

    def test_electron_file_origin_accepted_on_loopback_bind(self):
        # A file:// page sends no Origin on fetch but "file://" on the
        # WebSocket handshake, which is how live signals connect.
        client, _ = _client(host="localhost", port=1112)
        assert client.get(PROBE, headers={"Origin": FILE_ORIGIN}).status_code == 200

    def test_non_loopback_default_excludes_file_origin(self):
        origins = default_allowed_origins("10.0.0.5", 1112)
        assert FILE_ORIGIN not in origins
        client, _ = _client(host="10.0.0.5", port=1112)
        assert client.get(PROBE, headers={"Origin": FILE_ORIGIN}).status_code == 403

    def test_non_loopback_default_excludes_null_origin(self):
        origins = default_allowed_origins("10.0.0.5", 1112)
        assert "http://10.0.0.5:1112" in origins
        assert NULL_ORIGIN not in origins
        client, _ = _client(host="10.0.0.5", port=1112)
        assert client.get(PROBE, headers={"Origin": NULL_ORIGIN}).status_code == 403

    def test_all_interfaces_default_has_no_unspecified_address(self):
        origins = default_allowed_origins("0.0.0.0", 1112)
        assert not any("0.0.0.0" in o for o in origins)
        assert NULL_ORIGIN not in origins
        assert "http://localhost:1112" in origins

    def test_ipv6_literal_is_bracketed(self):
        assert "http://[::1]:1112" in default_allowed_origins("::1", 1112)


class Test_Configuration:

    def test_env_var_is_used_when_nothing_explicit(self, monkeypatch):
        monkeypatch.setenv(ALLOWED_ORIGINS_ENV, "http://a.example, http://b.example:8080")
        _, bridge = _client()
        assert bridge.allowed_origins == ["http://a.example", "http://b.example:8080"]

    def test_explicit_argument_beats_env_var(self, monkeypatch):
        monkeypatch.setenv(ALLOWED_ORIGINS_ENV, "http://env.example")
        _, bridge = _client(allowed_origins=["http://arg.example"])
        assert bridge.allowed_origins == ["http://arg.example"]

    def test_empty_env_var_fails_at_startup_naming_the_variable(self, monkeypatch):
        monkeypatch.setenv(ALLOWED_ORIGINS_ENV, " , ")
        with pytest.raises(ValueError, match=ALLOWED_ORIGINS_ENV):
            FastAPIBridge()

    @pytest.mark.parametrize("bad", [
        "localhost:1112",            # no scheme
        "http://x.example/path",     # path
        "http://x.example/",         # trailing slash
        "ftp://x.example",           # wrong scheme
        "http://x.example?q=1",      # query
    ])
    def test_malformed_origin_is_rejected_with_an_example(self, bad):
        with pytest.raises(ValueError) as exc:
            parse_allowed_origins([bad])
        assert bad in str(exc.value)
        assert "http://localhost:1112" in str(exc.value)

    def test_wildcard_cannot_be_mixed_with_origins(self):
        with pytest.raises(ValueError, match=r"\*"):
            parse_allowed_origins(["*", "http://a.example"])

    def test_duplicates_collapse_preserving_order(self):
        assert parse_allowed_origins("http://a.example,http://b.example,http://a.example") == [
            "http://a.example", "http://b.example"]

    def test_null_token_is_accepted_as_configuration(self):
        assert parse_allowed_origins("http://a.example,null") == ["http://a.example", NULL_ORIGIN]

    def test_file_origin_is_a_valid_entry(self):
        assert parse_allowed_origins("file://") == [FILE_ORIGIN]
