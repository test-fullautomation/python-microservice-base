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
"""The scaffold emits a Manager GUI component (contract v1) for every
single-service project, and the component passes the GUI's own linter."""

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from MicroserviceBase.adapters.scaffold.generator import (
    MethodParam, MethodSpec, ScaffoldSpec, generate_scaffold,
)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GUI = os.path.join(REPO, "MicroserviceBase", "MicroserviceManagerGUI")
LINT = os.path.join(GUI, "tools", "endo-lint.js")


def _spec(**kw):
    base = dict(
        service_name="PowerSupply", version="1.2.0", language="python",
        short_desc="Bench DUT supply", gen_stubs=False,
        methods=[
            MethodSpec(name="SetVoltage", params=[MethodParam("volts", "double"), MethodParam("channel", "int")]),
            MethodSpec(name="SetOutput", params=[MethodParam("on", "bool")]),
            MethodSpec(name="Configure", params=[MethodParam("a", "string"), MethodParam("b", "int64"),
                                                 MethodParam("c", "list")]),
            MethodSpec(name="Readings", server_streaming=True),
        ],
    )
    base.update(kw)
    return ScaffoldSpec(**base)


def _component(files, folder="PowerSupply1.2.0"):
    return json.loads(files["ui/%s/component.json" % folder])


class Test_Generated:
    def test_component_and_readme_are_emitted(self):
        files = generate_scaffold(_spec())
        assert "ui/PowerSupply1.2.0/component.json" in files
        assert "ui/README.md" in files
        assert "POWER_SUPPLY_GUI=PowerSupply1.2.0" in files["ui/README.md"]

    def test_identity_and_binding(self):
        c = _component(generate_scaffold(_spec()))
        assert c["component"] == "bits.power-supply"
        assert c["layer"] == "bits"
        assert c["version"] == "1.2.0"
        assert c["binds"] == {"consul": "@self", "grpc": "power_supply.v1.PowerSupplyService"}
        assert c["requires"] == {"shell": "^2.3", "capabilities": ["grpc.call"]}
        assert c["renderer"] == "schema"

    def test_one_tile_per_method_with_typed_forms(self):
        tiles = {t["id"]: t for t in _component(generate_scaffold(_spec()))["tiles"]}
        assert set(tiles) == {"set-voltage", "set-output", "configure", "readings"}
        assert tiles["set-voltage"]["form"] == {"volts": "float", "channel": "int"}
        assert tiles["set-output"]["form"] == {"on": "bool"}
        assert tiles["configure"]["form"] == {"a": "string", "b": "int", "c": "string"}
        assert tiles["configure"]["size"] == "2x1"          # more than two fields
        assert tiles["set-voltage"]["resultPath"] == "result"
        assert tiles["readings"]["kind"] == "log" and tiles["readings"]["size"] == "4x1"

    def test_layer_is_configurable_and_validated(self):
        assert _component(generate_scaffold(_spec(ui_layer="signals")))["component"] == "signals.power-supply"
        assert _component(generate_scaffold(_spec(ui_layer="hardware")))["layer"] == "bits"

    def test_imported_proto_uses_its_service_name_and_reflection(self):
        proto = 'syntax = "proto3";\npackage bench.psu.v2;\n\nservice Supply {\n  rpc SetVoltage (A) returns (B);\n}\n'
        spec = _spec(proto_content_override=proto, proto_package_override="bench.psu.v2",
                     methods=[MethodSpec(name="SetVoltage", params=[MethodParam("volts", "double")])])
        c = _component(generate_scaffold(spec))
        assert c["binds"]["grpc"] == "bench.psu.v2.Supply"
        tile = c["tiles"][0]
        assert "form" not in tile and "resultPath" not in tile   # the GUI reads them via reflection

    def test_no_methods_gives_a_text_tile_and_no_capabilities(self):
        c = _component(generate_scaffold(_spec(methods=[])))
        assert c["requires"]["capabilities"] == []
        assert c["tiles"][0]["kind"] == "text"

    def test_cpp_projects_get_the_same_component(self):
        files = generate_scaffold(_spec(language="cpp"))
        assert _component(files)["binds"]["grpc"] == "power_supply.v1.PowerSupplyService"
        assert "C++ runtime does not register" in files["ui/README.md"]


class Test_Bridge:
    """The Service Creator wizard (POST /api/scaffold/generate-v2) passes ui_layer through."""

    def test_wizard_zip_contains_the_component(self):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        import base64
        import io
        import zipfile
        from fastapi.testclient import TestClient
        from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import FastAPIBridge

        bridge = FastAPIBridge(host="localhost", port=1112)
        client = TestClient(bridge._build_app() or bridge._app)
        r = client.post("/api/scaffold/generate-v2", json={
            "service_name": "PowerSupply", "version": "1.2.0", "language": "python",
            "gen_stubs": False, "ui_layer": "signals",
            "methods": [{"name": "SetVoltage", "params": [{"name": "volts", "type": "double"}]}],
        })
        body = r.json()
        assert body["status"] == "ok", body
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(body["zip_data"]))) as zf:
            c = json.loads(zf.read("PowerSupply/ui/PowerSupply1.2.0/component.json"))
        assert c["component"] == "signals.power-supply"
        assert c["tiles"][0]["form"] == {"volts": "float"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
class Test_Lint:
    """The generated manifests must pass the GUI's own linter (tools/endo-lint.js)."""

    @pytest.mark.parametrize("kw", [
        {},
        {"ui_layer": "signals"},
        {"methods": []},
        {"language": "cpp"},
    ])
    def test_generated_component_lints_clean(self, kw):
        c = _component(generate_scaffold(_spec(**kw)))
        tmp = tempfile.mkdtemp(prefix="ui_component_")
        try:
            path = os.path.join(tmp, "component.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(c, fh)
            run = subprocess.run(["node", LINT, path], capture_output=True, text=True, timeout=60)
            assert run.returncode == 0, run.stdout + run.stderr
            assert "0 error(s), 0 warning(s)" in run.stdout, run.stdout
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
