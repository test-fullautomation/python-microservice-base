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
"""Bench compositions: the per-user store and the /api/ui/compositions endpoints."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from MicroserviceBase.adapters.ui_bridge.compositions import (  # noqa: E402
    COMPOSITIONS_DIR_ENV,
    CompositionError,
    CompositionStore,
    default_dir,
)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIXTURES = os.path.join(REPO, "MicroserviceBase", "MicroserviceManagerGUI", "test", "endo", "fixtures", "bench",
                        "compositions")

COMP = {
    "composition": "bench07/operator",
    "shell": "^2.3",
    "role": "user",
    "components": [{"from": "consul", "service": "session-service"}],
}


class Test_Store:

    def test_put_get_list_delete(self, tmp_path):
        store = CompositionStore(tmp_path)
        assert store.list() == []
        path = store.put("bench07", "user", COMP)
        assert path == tmp_path / "bench07" / "user.json"
        assert store.get("bench07", "user") == COMP
        assert [(e["bench"], e["role"], e["composition"]) for e in store.list()] == [
            ("bench07", "user", "bench07/operator")]
        assert store.delete("bench07", "user") is True
        assert store.get("bench07", "user") is None
        assert not (tmp_path / "bench07").exists()   # empty bench folder removed
        assert store.delete("bench07", "user") is False

    def test_put_replaces(self, tmp_path):
        store = CompositionStore(tmp_path)
        store.put("b", "dev", COMP)
        store.put("b", "dev", dict(COMP, title="Two"))
        assert store.get("b", "dev")["title"] == "Two"
        assert not list(tmp_path.rglob("*.tmp"))

    @pytest.mark.parametrize("bench,role", [
        ("../etc", "user"), ("a/b", "user"), ("", "user"), (".", "user"), ("x" * 65, "user"),
        ("bench07", "operator"), ("bench07", "../user"),
    ])
    def test_names_that_are_not_plain_file_names_are_refused(self, tmp_path, bench, role):
        with pytest.raises(CompositionError):
            CompositionStore(tmp_path).put(bench, role, COMP)

    @pytest.mark.parametrize("body", [[], "x", {}, {"components": {}}, {"components": ["a"]}])
    def test_bodies_that_cannot_be_compositions_are_refused(self, tmp_path, body):
        with pytest.raises(CompositionError):
            CompositionStore(tmp_path).put("b", "user", body)

    def test_oversized_body_is_refused(self, tmp_path):
        big = dict(COMP, title="x" * (300 * 1024))
        with pytest.raises(CompositionError, match="larger"):
            CompositionStore(tmp_path).put("b", "user", big)

    def test_env_overrides_the_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv(COMPOSITIONS_DIR_ENV, str(tmp_path))
        assert default_dir() == tmp_path
        monkeypatch.delenv(COMPOSITIONS_DIR_ENV)
        assert default_dir().parts[-2:] == ("devatservgui", "compositions")

    def test_the_prototype_compositions_are_storable(self, tmp_path):
        store = CompositionStore(tmp_path)
        for name in ("operator", "signals", "testdev", "lint"):
            with open(os.path.join(FIXTURES, name + ".json"), encoding="utf-8") as fh:
                comp = json.load(fh)
            bench, _ = comp["composition"].split("/")
            store.put(bench, comp["role"], comp)
        assert len(store.list()) == 4


class Test_Endpoints:

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient
        from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import FastAPIBridge
        monkeypatch.setenv(COMPOSITIONS_DIR_ENV, str(tmp_path))
        bridge = FastAPIBridge(host="localhost", port=1112)
        return TestClient(bridge._build_app() or bridge._app)

    def test_round_trip(self, client, tmp_path):
        r = client.get("/api/ui/compositions")
        assert r.json() == {"status": "ok", "dir": str(tmp_path), "compositions": []}
        r = client.put("/api/ui/compositions/bench07/user", json=COMP)
        assert r.json()["status"] == "ok"
        r = client.get("/api/ui/compositions/bench07/user")
        assert r.json()["composition"] == COMP
        listed = client.get("/api/ui/compositions").json()["compositions"]
        assert [(e["bench"], e["role"]) for e in listed] == [("bench07", "user")]
        assert client.delete("/api/ui/compositions/bench07/user").json()["status"] == "ok"
        r = client.get("/api/ui/compositions/bench07/user").json()
        assert r["status"] == "error" and r["code"] == "not_found"

    def test_invalid_names_and_bodies_are_errors(self, client, tmp_path):
        r = client.put("/api/ui/compositions/bench07/operator", json=COMP).json()
        assert r["status"] == "error" and r["code"] == "invalid"
        r = client.put("/api/ui/compositions/bench07/user", json={"components": "x"}).json()
        assert r["status"] == "error" and "components" in r["error"]
        assert not any(tmp_path.iterdir())

    def test_delete_of_a_missing_composition_is_not_found(self, client):
        r = client.delete("/api/ui/compositions/nope/user").json()
        assert r["status"] == "error" and r["code"] == "not_found"
