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
Generate a Manager GUI component (``component.json``) from ``.proto`` files.

For a service that already exists -- C++ or Python, with or without the
scaffold -- this writes the declarative panel the Manager GUI shows for it:
one command form per unary RPC, typed from the request message, and one
log per server-streaming RPC. Nothing in it runs code, so there is nothing
to build.

    python -m MicroserviceBase.tools.ui_component \\
        --proto proto/power_device.proto --proto ../libs/proto/config_device.proto \\
        --title "Power supply" --folder PowerService1.0.0 --out gui

* The first ``--proto`` is the service's own; later ones are services the
  same binary also serves (they are bound too, and their forms come after).
* Field labels come from the field names; ``>= a`` / ``<= b`` in a field's
  comment become the form's bounds, an ``int32 channel`` defaults to 1.
* A unary RPC whose request is at most a ``channel`` and whose response has
  a numeric ``value`` shows that value (``resultPath``); others show the
  whole response.
* ``--live`` adds a live-status tile polling those read RPCs on channel 1.
  It is off by default: polling talks to the device every few seconds.

Message types the parser does not resolve (imported or nested messages)
fall back to a ``json`` field, and the form takes the raw JSON there.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

LAYERS = ("operator", "session", "config", "execution", "runner", "signals", "bits")

_SCALAR = {
    "double": "float", "float": "float",
    "int32": "int", "int64": "int", "uint32": "int", "uint64": "int",
    "sint32": "int", "sint64": "int", "fixed32": "int", "fixed64": "int",
    "sfixed32": "int", "sfixed64": "int",
    "bool": "bool", "string": "string", "bytes": "string",
}


# ----------------------------------------------------------------------
# A small proto3 reader: packages, flat messages, enums, services
# ----------------------------------------------------------------------

def parse_proto(text: str) -> dict:
    """``{package, messages: {name: [field]}, enums: set, services: [{name, rpcs}]}``.

    A field is ``{name, type, repeated, comment}``; an RPC is
    ``{name, request, response, client_streaming, server_streaming}``.
    """
    pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.M)
    out = {"package": pkg.group(1) if pkg else "", "messages": {}, "enums": set(), "services": []}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"\s*(message|enum|service)\s+(\w+)\s*\{(.*)$", line)
        if not m:
            i += 1
            continue
        kind, name, rest = m.groups()
        body, depth, j = [rest], 1 + rest.count("{") - rest.count("}"), i + 1
        while depth > 0 and j < len(lines):
            body.append(lines[j])
            depth += lines[j].count("{") - lines[j].count("}")
            j += 1
        i = j
        if kind == "enum":
            out["enums"].add(name)
        elif kind == "message":
            out["messages"][name] = _fields(body)
        else:
            out["services"].append({"name": name, "rpcs": _rpcs("\n".join(body))})
    return out


def _fields(body: List[str]) -> List[dict]:
    fields = []
    for line in body:
        code, _, comment = line.partition("//")
        # several fields may share a line: "{ int32 a = 1; string b = 2; }"
        for part in code.replace("{", ";").replace("}", ";").split(";"):
            m = re.match(r"\s*(repeated\s+)?([\w.]+)\s+(\w+)\s*=\s*\d+", part)
            if m and m.group(2) not in ("message", "enum", "option", "reserved"):
                fields.append({"name": m.group(3), "type": m.group(2), "repeated": bool(m.group(1)),
                               "comment": comment.strip()})
    return fields


def _rpcs(body: str) -> List[dict]:
    rpcs = []
    for m in re.finditer(r"\brpc\s+(\w+)\s*\(\s*(stream\s+)?([\w.]+)\s*\)\s*returns\s*\(\s*(stream\s+)?([\w.]+)\s*\)",
                         body):
        rpcs.append({"name": m.group(1), "request": m.group(3), "response": m.group(5),
                     "client_streaming": bool(m.group(2)), "server_streaming": bool(m.group(4))})
    return rpcs


# ----------------------------------------------------------------------
# Forms
# ----------------------------------------------------------------------

def _kebab(name: str) -> str:
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "x"


def _label(name: str) -> str:
    """``SetOutputEnabled`` -> ``Set output enabled``; acronyms (``IO``) keep their case."""
    words = re.sub(r"[_\s]+", " ", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)).split()
    words = [w if i == 0 or not re.fullmatch(r"[A-Z][a-z0-9]*", w) else w.lower()
             for i, w in enumerate(words)]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def _field_spec(f: dict, proto: dict) -> dict:
    t = f["type"].rsplit(".", 1)[-1]
    if f["repeated"]:
        ftype = "json"
    elif f["type"] in _SCALAR:
        ftype = _SCALAR[f["type"]]
    elif t in proto["enums"]:
        ftype = "string"        # gRPC JSON takes the enum value's name
    else:
        ftype = "json"
    spec = {"type": ftype, "label": _label(f["name"])}
    c = f["comment"]
    lo = re.search(r">=\s*(-?\d+(?:\.\d+)?)", c)
    hi = re.search(r"<=\s*(-?\d+(?:\.\d+)?)", c)
    if ftype in ("int", "float"):
        if lo:
            spec["min"] = float(lo.group(1)) if ftype == "float" else int(float(lo.group(1)))
        if hi:
            spec["max"] = float(hi.group(1)) if ftype == "float" else int(float(hi.group(1)))
        if f["name"] == "channel" and ftype == "int":
            spec["default"] = 1
    return spec


def _comment_options(comment: str) -> Optional[list]:
    """``0-> RS232; 1-> client`` (or ``0 = off, 1 = on``) in a field comment -> fixed choices."""
    found = re.findall(r"(-?\d+)\s*(?:->|=>|=|:)\s*([A-Za-z][^;,]*?)\s*(?=;|,|$|\s-?\d+\s*(?:->|=>|=|:))", comment)
    if len(found) < 2:
        return None
    return [{"value": int(v), "label": label.strip()} for v, label in found]


def _int_field(fields: List[dict], skip=("errorcode", "error", "status", "code")) -> Optional[dict]:
    for f in fields:
        if _SCALAR.get(f["type"]) == "int" and not f["repeated"] and f["name"].lower() not in skip:
            return f
    return None


def _string_field(fields: List[dict]) -> Optional[dict]:
    for f in fields:
        if f["type"] == "string" and not f["repeated"]:
            return f
    return None


class _Rpcs:
    """Every RPC of the bound services by name, with its call string."""

    def __init__(self):
        self.by_name: Dict[str, tuple] = {}

    def add(self, name: str, call: str, rpc: dict, proto: dict):
        self.by_name.setdefault(name, (call, rpc, proto))

    def get(self, name: str):
        return self.by_name.get(name)

    def msg(self, entry, which: str) -> List[dict]:
        _, rpc, proto = entry
        return proto["messages"].get(rpc[which].rsplit(".", 1)[-1], [])


def _dropdown(rpcs: "_Rpcs", stem: str, field: dict) -> Optional[dict]:
    """``optionsFrom`` (+ ``current``) for an index of ``<stem>``, when the service lists them:
    ``Get<stem>_ListCount`` gives the count, ``Get<stem>_Name`` names each index,
    ``Get<stem>`` the selected one.

    The options are indexes 0 .. count-1, the way a service's own combo box
    fills them.  Comments such as "max index" or "1-n" are not trusted: they
    often disagree with the code, and an index past the end can crash a
    service that does not check it."""
    count = rpcs.get(f"Get{stem}_ListCount") or rpcs.get(f"Get{stem}ListCount") or rpcs.get(f"Get{stem}Count")
    if not count:
        return None
    count_out = _int_field(rpcs.msg(count, "response"))
    if not count_out:
        return None
    src = {"count": {"rpc": count[0], "path": count_out["name"]}}
    reload = []
    # A count that takes another setting (the sub-devices of a device type,
    # DeviceTypeRequest): read the list again after its setter (SetDeviceType).
    # The argument itself is left at its default: services differ in what it
    # means (the BITS services read it as the unit, not the device type, and
    # name the sub-devices of unit 0), and a wrong count asks for names past
    # the end of the list.
    count_in = rpcs.msg(count, "request")
    if count_in:
        req_type = count[1]["request"].rsplit(".", 1)[-1]
        other = re.sub(r"Request$", "", req_type)
        setter = rpcs.get(f"Set{other}")
        if setter and _int_field(count_in):
            reload.append(setter[0])
    name = rpcs.get(f"Get{stem}_Name") or rpcs.get(f"Get{stem}Name")
    if name:
        name_in, name_out = _int_field(rpcs.msg(name, "request")), _string_field(rpcs.msg(name, "response"))
        if name_in and name_out:
            src["name"] = {"rpc": name[0], "arg": name_in["name"], "path": name_out["name"]}
    out = {"optionsFrom": src}
    current = rpcs.get(f"Get{stem}")
    if current:
        cur = _int_field(rpcs.msg(current, "response"))
        if cur:
            out["current"] = {"rpc": current[0], "path": cur["name"]}
            # its own setter changes the selected one
            own = rpcs.get(f"Set{stem}")
            if own and own[0] not in reload:
                reload.append(own[0])
    if reload:
        out["reloadAfter"] = reload
    return out


def _stem_of(rpc_name: str) -> Optional[str]:
    """``SetDeviceType`` / ``GetDeviceType_Name`` -> ``DeviceType``."""
    m = re.match(r"^(?:Set|Get)([A-Za-z0-9]+?)(?:_?Name|_ListCount)?$", rpc_name)
    return m.group(1) if m else None


def _is_read(rpc: dict, proto: dict) -> bool:
    req = proto["messages"].get(rpc["request"].rsplit(".", 1)[-1], [])
    resp = proto["messages"].get(rpc["response"].rsplit(".", 1)[-1], [])
    takes = [f["name"] for f in req]
    has_value = any(f["name"] == "value" and _SCALAR.get(f["type"]) in ("int", "float") for f in resp)
    return has_value and takes in ([], ["channel"])


def _rpc_order(name: str) -> int:
    """Set-up first, then commands, then reads: the order a person works in."""
    n = name.lower()
    if n.startswith(("init", "connect", "open", "load")):
        return 0
    if n.startswith(("set", "enable", "disable", "start", "stop", "send", "write", "trigger")):
        return 1
    if n.startswith(("read", "get", "measure")):
        return 2
    return 1


_VERBS = ("Get", "Set", "Load", "Read", "Write", "Enable", "Disable", "Init")


def _topic(name: str) -> str:
    """What an RPC is about, without verb and list suffixes: ``GetSubDeviceType_Name``
    -> ``DeviceType``, ``LoadInterfaceConfig`` -> ``InterfaceConfig``, ``DisConnect`` -> ``Connect``."""
    n = re.sub(r"_?(ListCount|Name)$", "", name)
    for verb in _VERBS:
        if n.startswith(verb) and n[len(verb):len(verb) + 1].isupper():
            n = n[len(verb):]
            break
    for prefix in ("Sub", "Dis"):
        if n.startswith(prefix) and n[len(prefix):len(prefix) + 1].isupper():
            n = n[len(prefix):]
    return n


def _words(camel: str) -> List[str]:
    return re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", camel)


# Fewer tiles than this stay flat: headers would only add clutter.
GROUP_MIN_TILES = 7


def _group_tiles(tiles: List[dict], keys: List[tuple]) -> tuple:
    """Order the tiles group by group and describe the groups.

    ``keys[i]`` is ``(key, own, topic, declared)`` of ``tiles[i]``, or None for
    a tile in no group. The service's own RPCs form "Commands", "Readings"
    and "Streams" (open); every other bound service is split by topic --
    device type, interface, connection, in the order its proto declares them
    -- and starts collapsed: set-up that is done once, out of the way of the work.
    """
    order, members, topics, first_declared = [], {}, {}, {}
    for tile, key in zip(tiles, keys):
        if key is None:
            continue
        if key[0] not in members:
            order.append(key[:2])
            members[key[0]] = []
            topics[key[0]] = []
            first_declared[key[0]] = key[3]
        members[key[0]].append(tile)
        topics[key[0]].append(key[2])
        first_declared[key[0]] = min(first_declared[key[0]], key[3])
    # Own groups as they come; each other service's topics as its proto lists them.
    own_groups = [k for k in order if k[1]]
    other = [k for k in order if not k[1]]
    services = []
    for k in other:
        if k[0].split("|")[0] not in services:
            services.append(k[0].split("|")[0])      # bound services in their order
    other.sort(key=lambda k: (services.index(k[0].split("|")[0]), first_declared[k[0]]))
    order = own_groups + other
    ungrouped = [t for t, k in zip(tiles, keys) if k is None]
    groups, used = [], set()
    for key, own in order:
        if own:
            title = {"commands": "Commands", "readings": "Readings", "streams": "Streams"}[key]
            gid = key
        else:
            # The longest run of words the topics share: DeviceType + DeviceType -> "Device type".
            common = _words(topics[key][0])
            for t in topics[key][1:]:
                w = _words(t)
                n = 0
                while n < min(len(common), len(w)) and common[n] == w[n]:
                    n += 1
                common = common[:n] or common[:1]
            title = " ".join(common).capitalize() if common else key
            gid = _kebab(key.split("|")[-1]) or "group"
        while gid in used:
            gid += "-2"
        used.add(gid)
        group = {"id": gid, "title": title, "tiles": [t["id"] for t in members[key]]}
        if not own:
            group["collapsed"] = True
        groups.append(group)
    ordered = ungrouped + [t for key, _ in order for t in members[key]]
    return ordered, groups


def build_component(protos: List[dict], *, title: str, component: str, layer: str,
                    version: str = "1.0.0", description: str = "", live: bool = False) -> dict:
    """The component manifest for ``protos`` (the first is the service's own)."""
    binds, tiles, used, reads, keys = [], [], set(), [], []
    # Every RPC by name with its call string: the first bound service's
    # methods by name, the others qualified with their service.
    rpcs, first_full = _Rpcs(), None
    for proto in protos:
        for svc in proto["services"]:
            full = f"{proto['package']}.{svc['name']}" if proto["package"] else svc["name"]
            first_full = first_full or full
            for rpc in svc["rpcs"]:
                rpcs.add(rpc["name"], rpc["name"] if full == first_full else f"{full}/{rpc['name']}", rpc, proto)
    for proto in protos:
        for svc in proto["services"]:
            full = f"{proto['package']}.{svc['name']}" if proto["package"] else svc["name"]
            binds.append(full)
            first = len(binds) == 1
            # streams (wide log tiles) after the forms
            for rpc in sorted(svc["rpcs"], key=lambda r: (3 if r["server_streaming"] else _rpc_order(r["name"]))):
                if rpc["client_streaming"]:
                    continue        # a form cannot feed a request stream
                call = rpc["name"] if first else f"{full}/{rpc['name']}"
                tid = _kebab(rpc["name"])
                if tid in used:
                    tid = _kebab(svc["name"]) + "-" + tid
                used.add(tid)
                # Its group: the service's own RPCs by what they do, another
                # service's by topic (first word of it: Device, Interface, Connect).
                topic = _topic(rpc["name"])
                declared = svc["rpcs"].index(rpc)
                if first:
                    role = 3 if rpc["server_streaming"] else _rpc_order(rpc["name"])
                    keys.append(({3: "streams", 2: "readings"}.get(role, "commands"), True, topic, declared))
                else:
                    first_word = (_words(topic) or [topic])[0]
                    keys.append((f"{full}|{first_word}", False, topic, declared))
                if rpc["server_streaming"]:
                    tiles.append({"id": tid, "size": "4x1", "kind": "log",
                                  "title": f"{_label(rpc['name'])} (stream)", "rpc": call})
                    continue
                req = proto["messages"].get(rpc["request"].rsplit(".", 1)[-1], [])
                form = {f["name"]: _field_spec(f, proto) for f in req}
                # Dropdowns: choices named in the field's comment, or listed by the service.
                stem = _stem_of(rpc["name"])
                for f in req:
                    spec = form[f["name"]]
                    if spec["type"] != "int":
                        continue
                    fixed = _comment_options(f["comment"])
                    listed = _dropdown(rpcs, stem, f) if stem and len(req) == 1 else None
                    if listed and rpc["name"].endswith(("_ListCount", "ListCount", "Count")):
                        listed = None      # the count's own argument is not one of its items
                    if fixed:
                        spec["options"] = fixed
                        getter = rpcs.get(f"Get{stem}") if stem and rpc["name"].startswith("Set") else None
                        got = _int_field(rpcs.msg(getter, "response")) if getter else None
                        if got:
                            spec["current"] = {"rpc": getter[0], "path": got["name"]}
                    elif listed:
                        spec.update(listed)
                        if rpc["name"].startswith("Get"):
                            spec.pop("current", None)   # Get<X>_Name: pick any, not the selected one
                            own = rpcs.get(f"Set{stem}")
                            keep = [r for r in spec.get("reloadAfter", []) if not own or r != own[0]]
                            if keep:
                                spec["reloadAfter"] = keep
                            else:
                                spec.pop("reloadAfter", None)
                tile = {"id": tid, "size": "2x1" if len(form) >= 2 else "1x1",
                        "kind": "command-form", "title": _label(rpc["name"]),
                        "call": call, "submitLabel": _label(rpc["name"])}
                if form:
                    tile["form"] = form
                if _is_read(rpc, proto):
                    tile["resultPath"] = "value"
                    reads.append((rpc, call, req))
                tiles.append(tile)
    groups = []
    if len(tiles) >= GROUP_MIN_TILES:
        tiles, groups = _group_tiles(tiles, keys)
    if live and reads:
        fields = []
        for rpc, call, req in reads:
            field = {"label": _label(rpc["name"]), "rpc": call, "path": "value", "digits": 3}
            if req:
                field["args"] = {"channel": 1}
            fields.append(field)
        tiles.insert(0, {"id": "live", "size": "2x1", "kind": "live-status",
                         "title": "Live readings (channel 1)", "fields": fields})
    if not tiles:
        tiles.append({"id": "about", "size": "4x1", "kind": "text", "text": f"{title} has no RPCs."})
    manifest = {
        "component": component,
        "version": version,
        "layer": layer,
        "title": title,
        "requires": {"shell": "^2.3", "capabilities": ["grpc.call"] if binds else []},
        "binds": {"consul": "@self", "grpc": binds if len(binds) > 1 else (binds[0] if binds else [])},
        "tiles": tiles,
        **({"groups": groups} if groups else {}),
        "dock": ["api", "details"],
        "renderer": "schema",
    }
    if description:
        manifest["description"] = description
    return manifest


README = """\
# {title}: Manager GUI component

`{folder}/component.json` is this service's panel in the Manager GUI (Bench
Endoskeleton component contract v1). It is declarative: the GUI renders the
tiles, nothing here runs code, nothing has to be built.

Generated from: {sources}

    python -m MicroserviceBase.tools.ui_component {args}

Regenerate after the protos change; hand edits are lost then.

## Load it in the Manager GUI

1. Copy `{folder}/` into the Manager GUI's `web/services/`, or into
   `%APPDATA%/DevAtServGUI/web-services/` of an installed GUI.
2. Tell the GUI which folder belongs to the service, one of:
   - the service registers `Meta.gui = {folder}` in Consul: set the
     environment variable `<PREFIX>GUI={folder}` (needs a MicroserviceBase
     whose ServiceRunner registers `Meta.gui`);
   - or, on the bench, name the folder in the composition entry:
     `{{ "from": "consul", "service": "<consul name>", "gui": "{folder}" }}`.
3. Check it, from the Manager GUI folder:
   `node tools/endo-lint.js web/services/{folder}/component.json`
"""


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Manager GUI component.json from .proto files.")
    ap.add_argument("--proto", action="append", required=True,
                    help="a .proto file; the first is the service's own (repeatable)")
    ap.add_argument("--title", required=True, help="title shown in the GUI")
    ap.add_argument("--folder", required=True, help="GUI folder name, e.g. PowerService1.0.0")
    ap.add_argument("--out", default=".", help="directory to create <folder>/ in")
    ap.add_argument("--component", help="component id <layer>.<name> (default from the folder)")
    ap.add_argument("--layer", default="bits", choices=LAYERS)
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--description", default="")
    ap.add_argument("--live", action="store_true", help="add a live-status tile polling read RPCs")
    args = ap.parse_args(argv)

    protos = [parse_proto(Path(p).read_text(encoding="utf-8", errors="replace")) for p in args.proto]
    name = re.sub(r"\d+(\.\d+)*$", "", args.folder)
    component = args.component or f"{args.layer}.{_kebab(name)}"
    if not component.startswith(args.layer + "."):
        ap.error(f"--component must start with the layer: {args.layer}.<name>")
    manifest = build_component(protos, title=args.title, component=component, layer=args.layer,
                               version=args.version, description=args.description, live=args.live)
    target = Path(args.out) / args.folder
    target.mkdir(parents=True, exist_ok=True)
    (target / "component.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8", newline="\n")
    shown = " ".join(a if " " not in a else f'"{a}"' for a in (argv if argv is not None else sys.argv[1:]))
    (target / "README.md").write_text(README.format(
        title=args.title, folder=args.folder, args=shown,
        sources=", ".join(f"`{Path(p).name}`" for p in args.proto)), encoding="utf-8", newline="\n")
    n_forms = sum(1 for t in manifest["tiles"] if t["kind"] == "command-form")
    print(f"{target / 'component.json'}: {len(manifest['tiles'])} tiles ({n_forms} forms), "
          f"binds {manifest['binds']['grpc']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
