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
"""gui_type "wasm": the scaffold emits the Manager GUI panel (gui_wasm/, Qt for
WebAssembly) and a component per service registration, for every layout."""

import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

from MicroserviceBase.adapters.scaffold.generator import (
    MethodParam, MethodSpec, ScaffoldSpec, ServiceBlock, generate_scaffold,
)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LINT = os.path.join(REPO, "MicroserviceBase", "MicroserviceManagerGUI", "tools", "endo-lint.js")

PANEL = ["gui_wasm/CMakeLists.txt", "gui_wasm/main.cpp", "gui_wasm/panel_spec.h",
         "gui_wasm/ServicePanel.h", "gui_wasm/ServicePanel.cpp",
         "gui_wasm/ServiceBridge.h", "gui_wasm/ServiceBridge.cpp",
         "gui_wasm/build_wasm.bat", "gui_wasm/build_wasm.sh", "gui_wasm/README.md"]


def _methods():
    return [
        MethodSpec(name="SetVoltage", params=[MethodParam("volts", "double"), MethodParam("channel", "int"),
                                              MethodParam("on", "bool"), MethodParam("tags", "list")]),
        MethodSpec(name="Ping"),
        MethodSpec(name="Readings", server_streaming=True),
    ]


def _spec(layout="single", **kw):
    base = dict(service_name="Bench", version="1.2.0", language="cpp", gui_type="wasm",
                gen_stubs=False, methods=_methods())
    if layout != "single":
        base.update(layout=layout, services=[ServiceBlock(name="PowerService", methods=_methods()),
                                             ServiceBlock(name="RelayService", methods=[MethodSpec(name="Switch")])])
    base.update(kw)
    return ScaffoldSpec(**base)


def _components(files):
    return {k: json.loads(v) for k, v in files.items() if k.startswith("ui/") and k.endswith("component.json")}


def _panel_spec(files):
    text = files["gui_wasm/panel_spec.h"]
    m = re.search(r'R"PANEL\((.*)\)PANEL"', text, re.S)
    assert m, text[:200]
    return json.loads(m.group(1))


def _declared(files):
    out = set()
    for k, v in files.items():
        if k.endswith(".proto"):
            pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", v, re.M).group(1)
            out.update(f"{pkg}.{s}" for s in re.findall(r"^\s*service\s+(\w+)", v, re.M))
    return out


def _bound(comp):
    g = comp["binds"]["grpc"]
    return g if isinstance(g, list) else [g]


LAYOUTS = [("single", "cpp"), ("single", "python"), ("monorepo", "cpp"), ("monorepo", "python"),
           ("multi_proto", "cpp")]


class Test_Files:
    @pytest.mark.parametrize("layout,language", LAYOUTS)
    def test_panel_and_components_are_emitted(self, layout, language):
        files = generate_scaffold(_spec(layout, language=language))
        for p in PANEL:
            assert p in files, p
        assert "ui/README.md" in files
        assert _components(files)

    @pytest.mark.parametrize("layout,language", LAYOUTS)
    def test_old_wasm_stubs_are_gone(self, layout, language):
        files = generate_scaffold(_spec(layout, language=language))
        stale = [k for k in files if "MainWidget" in k or k.startswith("wasm/") or k.startswith("GUIs/")
                 or k in ("build_wasm.bat", "build_wasm.sh", "client/build_wasm.bat", "client/build_wasm.sh")]
        assert not stale, stale

    def test_no_panel_without_wasm(self):
        files = generate_scaffold(_spec(gui_type="none"))
        assert not [k for k in files if k.startswith("gui_wasm/")]
        assert _components(files)["ui/Bench1.2.0/component.json"]["renderer"] == "schema"

    def test_no_machine_paths_in_build_scripts(self):
        files = generate_scaffold(_spec())
        for p in ("gui_wasm/build_wasm.bat", "gui_wasm/build_wasm.sh"):
            assert not re.search(r"[A-Z]:\\Project|/d/Project|Users\\", files[p]), p


class Test_Components:
    def test_single(self):
        files = generate_scaffold(_spec())
        c = _components(files)["ui/Bench1.2.0/component.json"]
        assert c["renderer"] == "wasm"
        assert c["binds"] == {"consul": "@self", "grpc": "bench.v1.BenchService"}
        panel = c["tiles"][0]
        assert panel["kind"] == "wasm" and panel["entry"] == "qt/bench_panel.js"
        assert 200 <= panel["minHeight"] <= 1400
        assert [t["rpc"] for t in c["tiles"] if t["kind"] == "log"] == ["Readings"]

    def test_monorepo_one_component_per_service(self):
        comps = _components(generate_scaffold(_spec("monorepo")))
        assert set(comps) == {"ui/PowerService1.2.0/component.json", "ui/RelayService1.2.0/component.json"}
        assert comps["ui/PowerService1.2.0/component.json"]["binds"]["grpc"] == "bench.v1.PowerService"
        assert comps["ui/RelayService1.2.0/component.json"]["binds"]["grpc"] == "bench.v1.RelayService"
        # one build for both
        assert {c["tiles"][0]["entry"] for c in comps.values()} == {"qt/bench_panel.js"}

    def test_multi_proto_binds_every_service(self):
        comps = _components(generate_scaffold(_spec("multi_proto")))
        c = comps["ui/Bench1.2.0/component.json"]
        assert c["binds"]["grpc"] == ["power_service.v1.PowerService", "relay_service.v1.RelayService"]
        # with several services bound, a stream names its service
        assert [t["rpc"] for t in c["tiles"] if t["kind"] == "log"] == ["power_service.v1.PowerService/Readings"]

    @pytest.mark.parametrize("layout,language", LAYOUTS)
    def test_bound_services_exist_in_the_protos(self, layout, language):
        files = generate_scaffold(_spec(layout, language=language))
        declared = _declared(files)
        for c in _components(files).values():
            assert set(_bound(c)) <= declared, (_bound(c), declared)

    def test_imported_proto_names(self):
        proto = ('syntax = "proto3";\npackage lab.power.v2;\nservice Supply {\n'
                 '  rpc Set (SetRequest) returns (SetReply);\n}\n'
                 'message SetRequest { double volts = 1; }\nmessage SetReply { int32 code = 1; }\n')
        files = generate_scaffold(_spec(service_name="Supply", proto_content_override=proto,
                                        proto_package_override="lab.power.v2",
                                        methods=[MethodSpec(name="Set", input_type="lab.power.v2.SetRequest")]))
        c = _components(files)["ui/Supply1.2.0/component.json"]
        assert c["binds"]["grpc"] == "lab.power.v2.Supply"
        method = _panel_spec(files)["services"][0]["methods"][0]
        assert method["request"] == "json"


class Test_PanelSpec:
    def test_methods_and_field_types(self):
        spec = _panel_spec(generate_scaffold(_spec()))
        assert spec["title"] == "Bench"
        svc = spec["services"][0]
        assert svc["service"] == "bench.v1.BenchService"
        by = {m["name"]: m for m in svc["methods"]}
        assert [(f["name"], f["type"]) for f in by["SetVoltage"]["fields"]] == \
            [("volts", "float"), ("channel", "int"), ("on", "bool"), ("tags", "string")]   # "list" is not a wizard type: string
        assert by["Ping"]["request"] == "none"
        assert by["Readings"]["streaming"] is True

    def test_monorepo_panel_holds_every_service_once(self):
        spec = _panel_spec(generate_scaffold(_spec("monorepo")))
        assert [s["service"] for s in spec["services"]] == ["bench.v1.PowerService", "bench.v1.RelayService"]

    def test_raw_string_cannot_be_closed_by_a_description(self):
        ms = [MethodSpec(name="Odd", description='ends )PANEL" early')]
        spec = _panel_spec(generate_scaffold(_spec(methods=ms)))
        assert spec["services"][0]["methods"][0]["name"] == "Odd"


class Test_Deploy:
    @pytest.mark.parametrize("layout,language", LAYOUTS)
    def test_nomad_declares_the_gui_folder(self, layout, language):
        files = generate_scaffold(_spec(layout, language=language))
        env = {}
        for k, v in files.items():
            if k.endswith(".nomad.hcl"):
                env.update(dict(re.findall(r'^\s*(\w+_GUI)\s*=\s*"([^"]+)"', v, re.M)))
        folders = {k.split("/")[1] for k in _components(files)}
        assert set(env.values()) == folders, env

    def test_build_scripts_install_every_component(self):
        files = generate_scaffold(_spec("monorepo"))
        bat, sh = files["gui_wasm/build_wasm.bat"], files["gui_wasm/build_wasm.sh"]
        for folder in ("PowerService1.2.0", "RelayService1.2.0"):
            assert f'call :install "{folder}"' in bat
            assert f'install_into "{folder}"' in sh
        assert "@@" not in bat and "@@" not in sh


class Test_Lint:
    """The generated manifests pass the GUI's own linter; the only warning is the wasm one."""

    @pytest.mark.parametrize("layout,language", LAYOUTS)
    def test_generated_components_lint(self, layout, language):
        comps = _components(generate_scaffold(_spec(layout, language=language)))
        tmp = tempfile.mkdtemp(prefix="wasm_panel_")
        try:
            for i, c in enumerate(comps.values()):
                path = os.path.join(tmp, f"c{i}.json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(c, fh)
                run = subprocess.run(["node", LINT, path], capture_output=True, text=True, timeout=60)
                assert run.returncode == 0, run.stdout + run.stderr
                assert "0 error(s), 1 warning(s)" in run.stdout, run.stdout
                assert "wasm tile" in run.stdout
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
