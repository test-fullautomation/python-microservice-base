"""Manager GUI panel for ``gui_type = "wasm"``: a Qt for WebAssembly module.

The panel is a GUI-only Qt Widgets project in ``gui_wasm/`` that the Manager
GUI shows in a ``wasm`` tile of the service's component. It never links the
service: it calls the service's gRPC methods through the GUI
(``window.callMicroservice``), so it works for Python and C++ services alike
and needs no gRPC, protobuf or vcpkg.

The C++ sources are fixed (``templates/cpp/wasm_panel/``); what depends on
the project is generated here:

* ``gui_wasm/panel_spec.h``: the services and RPCs the panel shows;
* ``ui/<folder>/component.json``: one per Consul registration, with the
  panel tile, a ``log`` tile per server-streaming RPC and ``binds.grpc``;
* the build scripts, which install the panel next to each component;
* ``<PREFIX>GUI`` in the Nomad jobs, so the service registers ``Meta.gui``.

Layouts:

* ``single``: one component binding the one service.
* ``multi_proto``: N services in one binary (one Consul registration), so one
  component binding all of them.
* ``monorepo``: N binaries, each registered on its own, so one component
  per service. They share the one panel build; the GUI tells the module
  which services its component binds (``Module.endoServices``) and the
  panel shows only those.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Dict, List

from ._template_loader import load_raw, load_template
from .shared import UI_LAYERS, _form_type, _kebab, _proto_type

if TYPE_CHECKING:
    from .generator import MethodSpec, ScaffoldSpec, ServiceBlock


_SNAKE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_2 = re.compile(r"([a-z0-9])([A-Z])")


def _snake(name: str) -> str:
    return _SNAKE_2.sub(r"\1_\2", _SNAKE_1.sub(r"\1_\2", name)).lower()


def _package_of(proto_text: str, fallback: str) -> str:
    m = re.search(r"^\s*package\s+([\w.]+)\s*;", proto_text or "", re.M)
    return m.group(1) if m else fallback


# ----------------------------------------------------------------------
# What the panel shows
# ----------------------------------------------------------------------

def _method_entry(m: "MethodSpec", imported: bool) -> dict:
    """One RPC in panel_spec.h."""
    entry = {"name": m.name, "description": m.description or "", "streaming": bool(m.server_streaming)}
    if m.server_streaming:
        return entry
    if m.params:
        entry["request"] = "fields"
        entry["fields"] = [{"name": p.name, "type": _form_type(_proto_type(p.type))} for p in m.params]
    elif imported or m.input_type:
        # The request fields of an imported message are not known here.
        entry["request"] = "json"
    else:
        entry["request"] = "none"
    return entry


def _service_entry(full_name: str, methods, imported: bool) -> dict:
    return {
        "service": full_name,
        "title": full_name.rsplit(".", 1)[-1],
        "methods": [_method_entry(m, imported) for m in methods],
    }


def _components(spec: "ScaffoldSpec", files: Dict[str, str]) -> List[dict]:
    """The components of the project: [{folder, title, prefix, services}]."""
    layout = (spec.layout or "monorepo") if spec.services and len(spec.services) > 1 else "single"
    if layout == "single":
        proto = files.get(f"proto/{spec.snake_name}.proto", "")
        imported = bool(spec.proto_content_override)
        grpc = f"{spec.service_name}Service"
        if imported:
            m = re.search(r"^\s*service\s+(\w+)", proto, re.M)
            if m:
                grpc = m.group(1)
        package = spec.proto_package_override or _package_of(proto, spec.proto_package)
        return [{
            "folder": f"{spec.service_name}{spec.version}",
            "title": spec.service_name,
            "prefix": spec.env_prefix,
            "services": [_service_entry(f"{package}.{grpc}", spec.methods, imported)],
        }]

    blocks: List["ServiceBlock"] = list(spec.services)
    if layout == "multi_proto":
        services = []
        for b in blocks:
            imported = bool(b.proto_content)
            package = _package_of(b.proto_content, f"{_snake(b.name)}.v1")
            services.append(_service_entry(f"{package}.{b.name}", b.methods, imported))
        return [{
            "folder": f"{spec.service_name}{spec.version}",
            "title": spec.service_name,
            "prefix": spec.env_prefix,
            "services": services,
        }]

    # monorepo: one shared proto, one binary (and Consul name) per service
    imported = bool(spec.proto_content_override)
    package = spec.proto_package_override or _package_of(spec.proto_content_override, spec.proto_package)
    return [{
        "folder": f"{b.name}{spec.version}",
        "title": b.name,
        "prefix": _snake(b.name).upper() + "_",
        "services": [_service_entry(f"{package}.{b.name}", b.methods, imported)],
    } for b in blocks]


def _min_height(services: List[dict]) -> int:
    """A tile height (px) that fits the tallest service page of the panel."""
    def page(s: dict) -> int:
        h = 0
        for m in s["methods"]:
            if m.get("streaming"):
                h += 60
            else:
                h += 70 + 32 * len(m.get("fields", [])) + (70 if m.get("request") == "json" else 0)
        return h
    tallest = max((page(s) for s in services), default=0)
    tabs = 34 if len(services) > 1 else 0
    return max(200, min(1400, 60 + tabs + tallest))


# ----------------------------------------------------------------------
# component.json
# ----------------------------------------------------------------------

def component_manifest(spec: "ScaffoldSpec", comp: dict, target: str) -> dict:
    """The component of one Consul registration: the panel and its streams."""
    layer = spec.ui_layer if getattr(spec, "ui_layer", "") in UI_LAYERS else "bits"
    names = [s["service"] for s in comp["services"]]
    several = len(names) > 1
    tiles = [{
        "id": "panel",
        "size": "4x1",
        "kind": "wasm",
        "title": comp["title"],
        "entry": f"qt/{target}.js",
        "minHeight": _min_height(comp["services"]),
    }]
    for s in comp["services"]:
        for m in s["methods"]:
            if not m.get("streaming"):
                continue
            rpc = f"{s['service']}/{m['name']}" if several else m["name"]
            tiles.append({"id": _kebab((s["title"] + "-" if several else "") + m["name"]),
                          "size": "4x1", "kind": "log", "title": f"{m['name']} (stream)", "rpc": rpc})
    manifest = {
        "component": f"{layer}.{_kebab(comp['title'])}",
        "version": spec.version,
        "layer": layer,
        "title": comp["title"],
        "requires": {"shell": "^2.3", "capabilities": ["grpc.call"]},
        # "@self": the service that declares this component through Meta.gui.
        "binds": {"consul": "@self", "grpc": names if several else names[0]},
        "tiles": tiles,
        "dock": ["api", "details"],
        "renderer": "wasm",
    }
    if spec.short_desc or spec.description:
        manifest["description"] = spec.short_desc or spec.description
    return manifest


def _ui_readme(spec: "ScaffoldSpec", comps: List[dict]) -> str:
    folders = "\n".join(f"- `{c['folder']}/component.json`: {c['title']}, "
                        f"declared with `{c['prefix']}GUI={c['folder']}`" for c in comps)
    return "\n".join([
        f"# {spec.service_name}: Manager GUI components",
        "",
        "Each folder here is the Manager GUI component of one service registration",
        "(Bench Endoskeleton component contract v1). Its main tile is the service's",
        "panel, a Qt for WebAssembly module built from `../gui_wasm/`:",
        "",
        folders,
        "",
        "## Install",
        "",
        "1. Build the panel and install it into the Manager GUI:",
        "   `set MM_SERVICES=<gui>\\web\\services` then `gui_wasm\\build_wasm.bat`",
        "   (Linux: `MM_SERVICES=<gui>/web/services gui_wasm/build_wasm.sh`). Each",
        "   folder gets its `component.json` and the panel in `qt/`.",
        "2. Declare it: the service registers `Meta.gui = <folder>` in Consul. The",
        "   environment variable above does that (Python and C++ runtimes alike);",
        "   the generated Nomad job sets it.",
        "3. Check it, from the Manager GUI folder:",
        "   `node tools/endo-lint.js web/services/<folder>/component.json`",
        "   (one warning is expected: a wasm tile runs its script in the GUI page).",
        "",
        "## Adjust",
        "",
        "- **The panel** is `gui_wasm/ServicePanel.cpp`; see `gui_wasm/README.md`.",
        "- **Tile height:** `minHeight` (px) of the `panel` tile; a Qt canvas does",
        "  not make its tile grow.",
        "- **Layer.** If the service belongs to another layer of the TAG layer",
        "  chart, change `layer` and the prefix of `component` together (rule R8).",
        "- **Bindings.** `binds.consul` is `@self`; never put a host, port or IP",
        "  there (rule R3).",
        "",
    ])


# ----------------------------------------------------------------------
# Nomad: <PREFIX>GUI next to <PREFIX>CONSUL_ADDR
# ----------------------------------------------------------------------

_CONSUL_LINE = re.compile(r'^(?P<indent>[ \t]*)(?P<prefix>\w+_)CONSUL_ADDR(?P<pad>[ \t]*)=[^\n]*\n', re.M)


def _with_gui_env(text: str, folders: Dict[str, str]) -> str:
    def add(m: "re.Match") -> str:
        folder = folders.get(m.group("prefix"))
        if not folder or f'{m.group("prefix")}GUI' in text:
            return m.group(0)
        pad = " " * max(1, len("CONSUL_ADDR") + len(m.group("pad")) - len("GUI"))
        return m.group(0) + f'{m.group("indent")}{m.group("prefix")}GUI{pad}= "{folder}"\n'
    return _CONSUL_LINE.sub(add, text)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def generate(spec: "ScaffoldSpec", files: Dict[str, str]) -> Dict[str, str]:
    """
Render the WebAssembly panel of a scaffold and its Manager GUI components.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Scaffold specification with ``gui_type == "wasm"``, any layout.

* ``files``

  / *Condition*: required / *Type*: Dict[str, str] /

  The files generated so far: the protos are read from it, and the Nomad
  jobs in it get ``<PREFIX>GUI``.

**Returns:**

* ``files``

  / *Type*: Dict[str, str] /

  New and changed files: ``gui_wasm/*``, ``ui/<folder>/component.json``,
  ``ui/README.md`` and the updated ``*.nomad.hcl``.
    """
    comps = _components(spec, files)
    target = f"{spec.snake_name}_panel"
    title = spec.service_name

    services: List[dict] = []
    seen = set()
    for c in comps:
        for s in c["services"]:
            if s["service"] not in seen:
                seen.add(s["service"])
                services.append(s)
    spec_json = json.dumps({"title": title, "services": services}, indent=2, ensure_ascii=False)
    if ')PANEL"' in spec_json:   # would end the raw string literal early
        spec_json = spec_json.replace(')PANEL"', ') PANEL"')

    out: Dict[str, str] = {
        "gui_wasm/panel_spec.h": (
            "// panel_spec.h - the services and RPCs of the Manager GUI panel.\n"
            "// Generated by the MicroserviceBase scaffold from the project's protos;\n"
            "// ServicePanel builds its window from it.\n\n"
            "#pragma once\n\n"
            f'static const char *const PANEL_SPEC = R"PANEL({spec_json})PANEL";\n'
        ),
        "gui_wasm/ServicePanel.h": load_raw("cpp/wasm_panel/ServicePanel.h.tmpl"),
        "gui_wasm/ServicePanel.cpp": load_raw("cpp/wasm_panel/ServicePanel.cpp.tmpl"),
        "gui_wasm/ServiceBridge.h": load_raw("cpp/wasm_panel/ServiceBridge.h.tmpl"),
        "gui_wasm/ServiceBridge.cpp": load_raw("cpp/wasm_panel/ServiceBridge.cpp.tmpl"),
        "gui_wasm/main.cpp": load_raw("cpp/wasm_panel/main.cpp.tmpl"),
        "gui_wasm/CMakeLists.txt": load_template(
            "cpp/wasm_panel/CMakeLists.txt.tmpl", title=title, target=target,
            version=re.sub(r"[^0-9.].*$", "", spec.version) or "1.0.0"),
        "gui_wasm/build_wasm.bat": load_template(
            "cpp/wasm_panel/build_wasm.bat.tmpl", title=title, target=target,
            install_calls="\n".join(f'    call :install "{c["folder"]}"' for c in comps)),
        "gui_wasm/build_wasm.sh": load_template(
            "cpp/wasm_panel/build_wasm.sh.tmpl", title=title, target=target,
            install_calls_sh="\n".join(f'    install_into "{c["folder"]}"' for c in comps)),
        "gui_wasm/README.md": load_template(
            "cpp/wasm_panel/README.md.tmpl", title=title, target=target,
            install_layout="```\n" + "\n".join(
                f"web/services/{c['folder']}/component.json\n"
                f"web/services/{c['folder']}/qt/{target}.js\n"
                f"web/services/{c['folder']}/qt/{target}.wasm" for c in comps) + "\n```",
            gui_env="\n".join(f"`{c['prefix']}GUI={c['folder']}`" + (" (set by the Nomad job)." if spec.gen_nomad else ".")
                              for c in comps) + "\n"),
        "ui/README.md": _ui_readme(spec, comps),
    }
    for c in comps:
        out[f"ui/{c['folder']}/component.json"] = json.dumps(
            component_manifest(spec, c, target), indent=2, ensure_ascii=False) + "\n"

    folders = {c["prefix"]: c["folder"] for c in comps}
    for path, text in files.items():
        if path.endswith(".nomad.hcl"):
            updated = _with_gui_env(text, folders)
            if updated != text:
                out[path] = updated
    return out
