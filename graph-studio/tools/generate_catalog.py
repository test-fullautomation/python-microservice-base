#!/usr/bin/env python3
"""Generate the Graph Studio block catalog from the signals library source.

Phase C of Graph Studio — and the reference implementation of the
`generate_catalog.py` ask on the blocks-library story: the catalog is
OUTPUT derived from the code, never a hand-maintained copy (which drifted
twice, rev 1 and rev 2, proving the point).

Pure standard library, pure static analysis: the target file is AST-parsed,
never imported — so this runs anywhere, needs no venv with grpc, and cannot
execute repo code.

What is extracted per `@register_block("Name")` class:

* family      — from the `inputs`/`outputs` class attributes
                (no inputs -> source, no outputs -> sink, else function)
* doc         — first line of the class docstring
* ports       — the `inputs`/`outputs` tuples (rev-2 values are float|None)
* params      — from `__init__` + `build`:
                  params["k"] / cfg.params["k"]        -> required
                  params.get("k", default)             -> optional (+type from default)
                  int(...)/float(...) wrapping         -> int/float type
* device_ref  — a param whose value (directly or via a local variable) is
                used to index `ctx.device_adapters[...]`
* signal_ref  — the `signal_name` param of a class that touches
                `ctx.catalog_client` (cross-graph subscription)
* enum        — a param (or the local it is assigned to) that is checked
                with `x in ("a", "b", ...)` / `x not in (...)` against
                string constants: the tuple becomes `choices`

When the dataflow heuristics cannot see the intent (e.g. a block that talks
to a service through its own client instead of `ctx.device_adapters`), the
author can annotate the line that reads the param:

    self._svc = params["request_service"]   # graph-studio: device_ref
    policy = params.get("trigger", "on_change")  # graph-studio: enum on_change|every_write|edge
    name = params["service_name"]           # graph-studio: signal_ref

Supported annotations (several may be combined with `;`):
`device_ref`, `signal_ref`, `enum a|b|c`, `string|int|float|bool|list|object`
(type override), and `allowed_from <param>[.<field>]` — the value must be one
of the entries of another (list) param, e.g.

    self.allowlist = params.get("allowlist", [])   # list of {service, min, max}
    self.service_name = params["service_name"]     # graph-studio: allowed_from allowlist.service

An annotation always wins over inference. `list` / `object` are also inferred
from `params.get("k", [])` / `{}` defaults and `list(...)` / `dict(...)`
wrappers; the editor edits them as JSON text.

Usage:
    python generate_catalog.py <blocks.py | package-dir> [more paths...]
                               [-o blocks_catalog.json]
                               [--update-tool <graph-studio dir>]

Several files and/or directories may be given (directories are walked for
`*.py`, `tests/` and `__pycache__/` skipped); the result is one merged
catalog. A block type registered twice across the inputs is an error.

`--update-tool` writes blocks_catalog.json AND splices the same data into
DEFAULT_CATALOG in app/catalog.js — one source of truth for both copies.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from datetime import date
from pathlib import Path


# ─── AST helpers ─────────────────────────────────────────────────────


def _register_name(cls: ast.ClassDef) -> str | None:
    """Return the name from a @register_block("Name") decorator, if any."""
    for dec in cls.decorator_list:
        if (isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Name)
                and dec.func.id == "register_block"
                and dec.args
                and isinstance(dec.args[0], ast.Constant)):
            return str(dec.args[0].value)
    return None


def _port_tuple(cls: ast.ClassDef, attr: str) -> list[str]:
    """Read a class-level `inputs = ("in", ...)` tuple."""
    for node in cls.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == attr:
                    if isinstance(node.value, ast.Tuple):
                        return [str(e.value) for e in node.value.elts
                                if isinstance(e, ast.Constant)]
    return []


def _is_params_expr(node: ast.expr) -> bool:
    """True for `params` or `cfg.params` / `<x>.params`."""
    if isinstance(node, ast.Name) and node.id == "params":
        return True
    return isinstance(node, ast.Attribute) and node.attr == "params"


def _literal_type(node: ast.expr) -> str:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "bool"
        if isinstance(node.value, int):
            return "int"
        if isinstance(node.value, float):
            return "float"
        if isinstance(node.value, str):
            return "string"
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        return _literal_type(node.operand)
    if isinstance(node, (ast.List, ast.Tuple)):
        return "list"
    if isinstance(node, ast.Dict):
        return "object"
    return "string"


# `int(params["k"])` style wrappers → the param's type
_WRAPPER_TYPES = {"int": "int", "float": "float", "str": "string", "bool": "bool",
                  "list": "list", "tuple": "list", "dict": "object"}


_ANNOTATION_RE = re.compile(r"#\s*graph-studio:\s*(.+?)\s*$")


def _annotations(source: str) -> dict[int, str]:
    """Map line number -> `# graph-studio: <spec>` comment text."""
    out: dict[int, str] = {}
    for i, line in enumerate(source.splitlines(), start=1):
        m = _ANNOTATION_RE.search(line)
        if m:
            out[i] = m.group(1)
    return out


def _param_key_of(node: ast.expr, param_vars: dict[str, str]) -> str | None:
    """`params["k"]` / `cfg.params["k"]` / a local assigned from one -> "k"."""
    if (isinstance(node, ast.Subscript) and _is_params_expr(node.value)
            and isinstance(node.slice, ast.Constant)):
        return str(node.slice.value)
    if isinstance(node, ast.Name) and node.id in param_vars:
        return param_vars[node.id]
    if (isinstance(node, ast.Attribute) and node.attr in param_vars
            and isinstance(node.value, ast.Name) and node.value.id == "self"):
        return param_vars[node.attr]
    return None


def _string_choices(node: ast.expr) -> list[str] | None:
    """`("a", "b")` / `{"a", "b"}` / `["a", "b"]` of string constants -> list."""
    if isinstance(node, (ast.Tuple, ast.Set, ast.List)) and node.elts and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return [e.value for e in node.elts]
    return None


class _ParamCollector(ast.NodeVisitor):
    """Collect param usage from one function body."""

    def __init__(self) -> None:
        self.required: dict[str, str] = {}      # name -> type
        self.optional: dict[str, str] = {}      # name -> type
        self.order: list[str] = []
        self.param_vars: dict[str, str] = {}    # local var / self attr -> param name
        self.device_params: set[str] = set()
        self.choices: dict[str, list[str]] = {}  # name -> enum choices (inferred)
        self.lines: dict[str, int] = {}          # name -> first line it is read on
        self._wrap: list[str] = []              # int()/float() wrapper stack

    def _seen(self, name: str, node: ast.AST | None = None) -> None:
        if name not in self.order:
            self.order.append(name)
        if node is not None and name not in self.lines and hasattr(node, "lineno"):
            self.lines[name] = node.lineno

    # `x in ("a", "b")` / `x not in {...}`  → enum choices for the param behind x
    def visit_Compare(self, node: ast.Compare) -> None:
        if (len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn))
                and len(node.comparators) == 1):
            key = _param_key_of(node.left, self.param_vars)
            choices = _string_choices(node.comparators[0])
            if key and choices:
                self.choices.setdefault(key, choices)
        self.generic_visit(node)

    # params["k"]  → required
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_params_expr(node.value) and isinstance(node.slice, ast.Constant):
            key = str(node.slice.value)
            self._seen(key, node)
            typ = self._wrap[-1] if self._wrap else "string"
            self.required.setdefault(key, typ)
        # ctx.device_adapters[<expr>]
        if (isinstance(node.value, ast.Attribute)
                and node.value.attr == "device_adapters"):
            inner = node.slice
            if (isinstance(inner, ast.Subscript) and _is_params_expr(inner.value)
                    and isinstance(inner.slice, ast.Constant)):
                self.device_params.add(str(inner.slice.value))
            elif isinstance(inner, ast.Name) and inner.id in self.param_vars:
                self.device_params.add(self.param_vars[inner.id])
        self.generic_visit(node)

    # params.get("k", default)  → optional
    def visit_Call(self, node: ast.Call) -> None:
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and _is_params_expr(node.func.value)
                and node.args and isinstance(node.args[0], ast.Constant)):
            key = str(node.args[0].value)
            self._seen(key, node)
            typ = _literal_type(node.args[1]) if len(node.args) > 1 else "string"
            self.optional.setdefault(key, typ)
            self.generic_visit(node)
            return
        # int(...) / float(...) / list(...) / dict(...) wrappers give required params their type
        if isinstance(node.func, ast.Name) and node.func.id in _WRAPPER_TYPES:
            self._wrap.append(_WRAPPER_TYPES[node.func.id])
            self.generic_visit(node)
            self._wrap.pop()
            return
        self.generic_visit(node)

    # x = cfg.params["device"] / self.x = params.get("k", d)  → remember var → param
    def visit_Assign(self, node: ast.Assign) -> None:
        key = None
        v = node.value
        if (isinstance(v, ast.Subscript) and _is_params_expr(v.value)
                and isinstance(v.slice, ast.Constant)):
            key = str(v.slice.value)
        elif (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
              and v.func.attr == "get" and _is_params_expr(v.func.value)
              and v.args and isinstance(v.args[0], ast.Constant)):
            key = str(v.args[0].value)
        if key is not None and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name):
                self.param_vars[tgt.id] = key
            elif (isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name)
                  and tgt.value.id == "self"):
                self.param_vars[tgt.attr] = key
        self.generic_visit(node)


def _uses_attr(cls: ast.ClassDef, attr: str) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == attr
               for n in ast.walk(cls))


# ─── extraction ──────────────────────────────────────────────────────


_SCALAR_TYPES = ("string", "int", "float", "bool", "list", "object")


def _apply_annotation(param: dict, spec: str) -> None:
    """Overwrite a param entry from a `# graph-studio: <spec>[; <spec>...]` comment."""
    for part in spec.split(";"):
        part = part.strip()
        if not part:
            continue
        head, _, rest = part.partition(" ")
        head = head.strip().lower()
        rest = rest.strip()
        if head in ("device_ref", "signal_ref"):
            param["type"] = head
            param.pop("choices", None)
        elif head == "enum":
            choices = [c.strip() for c in rest.split("|") if c.strip()]
            if not choices:
                raise ValueError(f"annotation 'enum' needs choices a|b|c (got {part!r})")
            param["type"] = "enum"
            param["choices"] = choices
        elif head in _SCALAR_TYPES:
            param["type"] = head
            param.pop("choices", None)
        elif head == "allowed_from":
            # `allowed_from allowlist.service` → value must be one of
            # params.allowlist[*].service; `allowed_from names` → one of the
            # strings in params.names. The referenced param must be a list.
            src, _, field = rest.partition(".")
            if not src:
                raise ValueError(f"annotation 'allowed_from' needs <param>[.<field>] (got {part!r})")
            param["allowed_from"] = {"param": src.strip(), **({"field": field.strip()} if field else {})}
        else:
            raise ValueError(f"unknown graph-studio annotation {part!r}")


def extract_blocks(source_path: Path) -> list[dict]:
    """All `@register_block` classes of one file as catalog entries."""
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    notes = _annotations(source)
    blocks = []

    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        type_name = _register_name(cls)
        if type_name is None:
            continue

        inputs = _port_tuple(cls, "inputs")
        outputs = _port_tuple(cls, "outputs")
        family = ("source" if not inputs else "sink" if not outputs else "function")

        collector = _ParamCollector()
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name in ("__init__", "build"):
                collector.visit(node)
        # `x in (...)` checks may sit in step()/start() too — scan the whole class
        # for choices, but only for params already seen in __init__/build.
        choice_scan = _ParamCollector()
        choice_scan.param_vars = dict(collector.param_vars)
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                choice_scan.visit(node)
        for k, v in choice_scan.choices.items():
            collector.choices.setdefault(k, v)

        uses_catalog = _uses_attr(cls, "catalog_client")
        params = []
        for name in collector.order:
            required = name in collector.required
            typ = collector.required.get(name) or collector.optional.get(name, "string")
            entry = {"name": name, "type": typ, "required": required}
            if name in collector.device_params:
                entry["type"] = "device_ref"
            elif name == "signal_name" and uses_catalog:
                entry["type"] = "signal_ref"
            elif name in collector.choices and typ == "string":
                entry["type"] = "enum"
                entry["choices"] = collector.choices[name]
            note = notes.get(collector.lines.get(name, -1))
            if note:
                try:
                    _apply_annotation(entry, note)
                except ValueError as e:
                    raise SystemExit(f"{source_path}:{collector.lines[name]}: {e}") from e
            params.append(entry)

        doc = (ast.get_docstring(cls) or "").strip().split("\n")[0]
        blocks.append({
            "type": type_name,
            "family": family,
            "doc": doc,
            "inputs": [{"name": p, "type": "float"} for p in inputs],
            "outputs": [{"name": p, "type": "float"} for p in outputs],
            "params": params,
            "origin": "generated",
            "source": source_path.name,
        })

    return blocks


def _iter_sources(paths: list[Path]) -> list[Path]:
    """Expand files/directories into the ordered list of .py files to scan."""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*.py")):
                parts = {x.lower() for x in f.relative_to(p).parts}
                if "tests" in parts or "__pycache__" in parts or f.name.startswith("test_"):
                    continue
                out.append(f)
        elif p.is_file():
            out.append(p)
        else:
            raise SystemExit(f"not found: {p}")
    return out


def extract_catalog(paths: list[Path] | Path) -> dict:
    if isinstance(paths, Path):
        paths = [paths]
    sources = _iter_sources(paths)
    blocks: list[dict] = []
    owner: dict[str, Path] = {}
    for src in sources:
        for b in extract_blocks(src):
            if b["type"] in owner:
                raise SystemExit(
                    f"block type '{b['type']}' registered twice: {owner[b['type']]} and {src}")
            owner[b["type"]] = src
            blocks.append(b)

    # Sources relative to the folder the inputs share, so the committed
    # catalog names files (signal_graph/core/domain/blocks.py), not a
    # machine's checkout location.
    base = Path(os.path.commonpath([str(p if p.is_dir() else p.parent) for p in paths]))
    shown = [s.relative_to(base).as_posix() if s.is_relative_to(base) else s.name for s in sources]
    return {
        "catalog_version": f"generated-{date.today().isoformat()}",
        "generated_from": shown if len(shown) != 1 else shown[0],
        "generator": "graph-studio/tools/generate_catalog.py (AST, no imports)",
        "blocks": blocks,
    }


# ─── catalog.js splice (--update-tool) ───────────────────────────────


def splice_default_catalog(catalog_js: Path, data: dict) -> None:
    js = catalog_js.read_text(encoding="utf-8")
    marker = "const DEFAULT_CATALOG = "
    start = js.index(marker) + len(marker)
    depth = 0
    i = js.index("{", start)
    for j in range(i, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                break
    literal = json.dumps(
        {"catalog_version": data["catalog_version"], "blocks": data["blocks"]},
        indent=2,
    )
    catalog_js.write_text(js[:i] + literal + js[j + 1:], encoding="utf-8")


# ─── CLI ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("sources", type=Path, nargs="+",
                        help="blocks.py file(s) and/or package directories to scan")
    parser.add_argument("-o", "--out", type=Path, default=None)
    parser.add_argument("--update-tool", type=Path, default=None,
                        help="graph-studio dir: write blocks_catalog.json + splice app/catalog.js")
    args = parser.parse_args()

    data = extract_catalog(args.sources)
    print(f"extracted {len(data['blocks'])} block types from "
          f"{', '.join(str(s) for s in args.sources)}", file=sys.stderr)

    text = json.dumps(data, indent=4) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    if args.update_tool:
        (args.update_tool / "blocks_catalog.json").write_text(text, encoding="utf-8")
        splice_default_catalog(args.update_tool / "app" / "catalog.js", data)
        print(f"updated {args.update_tool}/blocks_catalog.json and app/catalog.js",
              file=sys.stderr)
    if not args.out and not args.update_tool:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
