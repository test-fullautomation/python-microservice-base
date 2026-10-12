"""Describe a Robot Framework suite or resource file as a grid, for the Manager GUI.

Run by path with the project's interpreter (the one the tests run with, so
the keywords resolve exactly as they will at run time)::

    python robot_grid.py <path/to/file.robot>   < file text on stdin

The text comes on stdin so unsaved editor content can be shown; the path is
where the file lives (relative imports resolve against it). Prints one JSON
object::

    {"ok": true,
     "grid": {"sections": [{"type", "title", "line", "rows" | "items"}]},
     "keywords": {key: {name, owner, owner_type, args, shortdoc, doc}},
     "imports": [{"type", "name", "line", "ok", "error", "keywords"}],
     "catalog": n}

A row is one statement: ``{"line", "depth", "type", "label", "assign",
"keyword", "kw", "cells", "missing", "comment"}``. ``kw`` is the key of the
keyword it calls in ``keywords`` (``null``: not found in the imports), and
every cell is ``{"v": value, "p": parameter or null, "kw": key of a keyword
this cell names (Run Keyword and friends)}``. Only the keywords the file
uses are sent in full; ``catalog`` says how many were found.

Nothing here writes: the grid is read-only (phase 1).

Where a keyword is defined, for an editor's *Go to Definition*::

    python robot_grid.py --define <path>   < {"text": ..., "name": ...}

``path`` is a suite, a resource or a flow file (``*.flow.json``: its
``imports`` are what it can call). ``name`` is the keyword as written in a
call, or an import's name. Prints ``{"ok", "found", "source", "line",
"name", "owner", "owner_type"}``; ``source`` is a file path, ``line`` 1-based
(or null when only the file is known).
"""

import hashlib
import json
import os
import re
import sys
import tempfile
import time

# This folder must not shadow anything the file imports.
if sys.path and os.path.abspath(sys.path[0] or ".") == os.path.dirname(os.path.abspath(__file__)):
    del sys.path[0]

CACHE_DIR = os.path.join(tempfile.gettempdir(), "mm_robot_grid_cache")
CACHE_TTL_S = 24 * 3600
MAX_RESOURCE_DEPTH = 6
_VAR_RE = re.compile(r"[$@&%]\{[^}]*\}")


def norm(name):
    """Robot's name matching: case, spaces and underscores do not count."""
    return re.sub(r"[\s_]+", "", str(name)).lower()


# --------------------------------------------------------------- the keywords

def _arg_dicts(spec_args):
    out = []
    for a in spec_args or []:
        types = a.get("types") or []
        out.append({"name": a.get("name", ""), "kind": a.get("kind", ""),
                    "required": bool(a.get("required")),
                    "default": a.get("defaultValue"),
                    "type": " | ".join(str(t) for t in types) if types else None})
    return out


def _libdoc(spec, cache_key_extra=""):
    """``{"name", "type", "keywords": [...]}`` for a library or resource, cached."""
    from robot.libdoc import LibraryDocumentation
    from robot.version import get_version
    path_mtime = os.path.getmtime(spec) if os.path.isfile(spec) else 0
    key = hashlib.sha1(json.dumps(["v2", spec, cache_key_extra, path_mtime, get_version(), sys.executable,
                                   os.environ.get("PYTHONPATH", "")]).encode("utf-8")).hexdigest()
    cached = os.path.join(CACHE_DIR, key + ".json")
    try:
        if time.time() - os.path.getmtime(cached) < CACHE_TTL_S:
            with open(cached, encoding="utf-8") as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    doc = LibraryDocumentation(spec).to_dictionary()
    data = {"name": doc.get("name", ""), "type": doc.get("type", ""), "source": doc.get("source") or None,
            "keywords": [{"name": k.get("name", ""), "args": _arg_dicts(k.get("args")),
                          "shortdoc": k.get("shortdoc", ""), "doc": (k.get("doc") or "")[:4000],
                          "source": k.get("source") or doc.get("source") or None,
                          "lineno": k.get("lineno") or None}
                         for k in doc.get("keywords") or []]}
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cached + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(cached + ".tmp", cached)
    except OSError:
        pass
    return data


def _resolve_name(name, base_dir):
    """An import name with ${CURDIR} filled in; None when other variables remain."""
    value = name.replace("${CURDIR}", base_dir.replace("\\", "/"))
    if _VAR_RE.search(value):
        return None
    return value


def _file_keywords(model):
    """The file's own keywords, from the (unsaved) text itself."""
    from robot.api.parsing import Token
    out = []
    for section in model.sections:
        if type(section).__name__ != "KeywordSection":
            continue
        for kw in section.body:
            if type(kw).__name__ != "Keyword":
                continue
            args, doc = [], ""
            for stmt in kw.body:
                t = type(stmt).__name__
                if t == "Arguments":
                    for value in stmt.get_values(Token.ARGUMENT):
                        args.append(_user_arg(value))
                elif t == "Documentation":
                    doc = stmt.value
            out.append({"name": kw.name, "args": args, "shortdoc": doc.split("\n")[0], "doc": doc[:4000],
                        "lineno": kw.lineno})
    return out


def _user_arg(value):
    name, _, default = value.partition("=")
    if value.startswith("@{"):
        return {"name": name[2:-1], "kind": "VAR_POSITIONAL", "required": False, "default": None, "type": None}
    if value.startswith("&{"):
        return {"name": name[2:-1], "kind": "VAR_NAMED", "required": False, "default": None, "type": None}
    has_default = "=" in value
    return {"name": name[2:-1] if name.startswith("${") else name, "kind": "POSITIONAL_OR_NAMED",
            "required": not has_default, "default": default if has_default else None, "type": None}


class Catalog:
    """Every keyword the file can call: BuiltIn, its libraries and resources
    (and theirs, since a resource's imports reach the suite), and its own."""

    def __init__(self):
        self.by_name = {}        # norm(name) -> [entry]
        self.by_owner = {}       # norm(owner) -> {norm(name): entry}
        self.embedded = []       # (regex, entry)
        self.imports = []
        self.count = 0
        self.variables = []      # [{name, value, source}] from Variables sections

    def add(self, owner, owner_type, keywords, alias=None):
        owner_name = alias or owner
        table = self.by_owner.setdefault(norm(owner_name), {})
        for kw in keywords:
            entry = dict(kw, owner=owner_name, owner_type=owner_type)
            entry["key"] = norm(owner_name) + "." + norm(kw["name"])
            self.by_name.setdefault(norm(kw["name"]), []).append(entry)
            table[norm(kw["name"])] = entry
            if "${" in kw["name"]:
                pattern = "".join(".+?" if part.startswith("${") else re.escape(part)
                                  for part in re.split(r"(\$\{[^}]*\})", kw["name"]))
                self.embedded.append((re.compile("^" + pattern + "$", re.I), entry))
            self.count += 1

    def find(self, name):
        if not name:
            return None
        n = norm(name)
        found = self.by_name.get(n)
        if found:
            # A file's own keywords win, then resources, then libraries (Robot's order).
            order = {"file": 0, "resource": 1, "library": 2}
            return sorted(found, key=lambda e: order.get(e["owner_type"], 3))[0]
        if "." in name:
            owner, _, kw = name.rpartition(".")
            entry = self.by_owner.get(norm(owner), {}).get(norm(kw))
            if entry:
                return entry
        for regex, entry in self.embedded:
            if regex.match(name.strip()):
                return entry
        return None


def _variables_of(model, source):
    """The variables a Variables section defines: ``[{name, value, source}]``."""
    out = []
    for section in model.sections:
        if type(section).__name__ != "VariableSection":
            continue
        for stmt in section.body:
            if type(stmt).__name__ == "Variable" and stmt.name:
                value = "    ".join(stmt.value) if isinstance(stmt.value, (list, tuple)) else str(stmt.value or "")
                out.append({"name": stmt.name.rstrip("= "), "value": value[:120], "source": source})
    return out


def build_catalog(model, path, text_is_resource):
    from robot.api.parsing import get_resource_model
    catalog = Catalog()
    base_dir = os.path.dirname(os.path.abspath(path))
    try:
        catalog.add("BuiltIn", "library", _libdoc("BuiltIn")["keywords"])
    except Exception as exc:  # noqa: BLE001
        catalog.imports.append({"type": "library", "name": "BuiltIn", "line": None, "ok": False, "error": str(exc)})
    seen = set()

    def imports_of(m, where, line_known, depth):
        for section in m.sections:
            if type(section).__name__ != "SettingSection":
                continue
            for stmt in section.body:
                t = type(stmt).__name__
                if t not in ("LibraryImport", "ResourceImport"):
                    continue
                record = {"type": "library" if t == "LibraryImport" else "resource", "name": stmt.name,
                          "line": stmt.lineno if line_known else None, "ok": False, "error": "", "keywords": 0,
                          "via": None if line_known else os.path.basename(where)}
                resolved = _resolve_name(stmt.name or "", os.path.dirname(where))
                if resolved is None:
                    record["error"] = "The name uses variables the grid cannot fill in."
                    catalog.imports.append(record)
                    continue
                if t == "LibraryImport":
                    spec = resolved
                    if spec.lower().endswith(".py") and not os.path.isabs(spec):
                        spec = os.path.normpath(os.path.join(os.path.dirname(where), spec))
                    if ("lib", spec, stmt.alias) in seen:
                        continue
                    seen.add(("lib", spec, stmt.alias))
                    try:
                        doc = _libdoc(spec)
                        catalog.add(doc["name"] or stmt.name, "library", doc["keywords"], alias=stmt.alias)
                        record.update(ok=True, keywords=len(doc["keywords"]), source=doc.get("source"))
                    except Exception as exc:  # noqa: BLE001 -- say which import, keep going
                        record["error"] = str(exc).splitlines()[0][:300]
                    catalog.imports.append(record)
                else:
                    rpath = resolved if os.path.isabs(resolved) else os.path.normpath(
                        os.path.join(os.path.dirname(where), resolved))
                    if ("res", rpath) in seen:
                        continue
                    seen.add(("res", rpath))
                    if not os.path.isfile(rpath):
                        record["error"] = f"No such file: {resolved}"
                        catalog.imports.append(record)
                        continue
                    record["source"] = rpath
                    try:
                        doc = _libdoc(rpath)
                        catalog.add(doc["name"] or os.path.splitext(os.path.basename(rpath))[0], "resource",
                                    doc["keywords"])
                        record.update(ok=True, keywords=len(doc["keywords"]))
                    except Exception as exc:  # noqa: BLE001
                        record["error"] = str(exc).splitlines()[0][:300]
                    catalog.imports.append(record)
                    if depth < MAX_RESOURCE_DEPTH:
                        try:
                            rmodel = get_resource_model(rpath)
                            catalog.variables += _variables_of(rmodel, os.path.basename(rpath))
                            imports_of(rmodel, rpath, False, depth + 1)
                        except Exception:  # noqa: BLE001 -- the resource's own record says enough
                            pass

    catalog.variables = _variables_of(model, os.path.basename(path))
    imports_of(model, os.path.abspath(path), True, 0)
    own = [dict(kw, source=os.path.abspath(path)) for kw in _file_keywords(model)]
    catalog.add(os.path.splitext(os.path.basename(path))[0], "file", own)
    return catalog


# ------------------------------------------------------------------ the rows

_RUN_VARIANT_OWNERS = ("builtin",)


def label_cells(entry, values, catalog, used, depth=0):
    """Pair call arguments with the keyword's parameters.

    Returns ``(cells, missing)``: every cell ``{"v", "p", "kw"}``, and the
    names of required parameters no value reached. A BuiltIn parameter
    ``name`` followed by ``*args`` (Run Keyword, Wait Until Keyword
    Succeeds, ...) names a keyword: the cells after it are that keyword's.
    """
    cells = [{"v": v, "p": None, "kw": None} for v in values]
    if entry is None:
        return cells, []
    spec = entry.get("args") or []
    positional = [a for a in spec if a["kind"] in ("POSITIONAL_ONLY", "POSITIONAL_OR_NAMED")]
    var_pos = next((a for a in spec if a["kind"] == "VAR_POSITIONAL"), None)
    named_ok = {a["name"]: a for a in spec if a["kind"] in ("POSITIONAL_OR_NAMED", "NAMED_ONLY")}
    var_named = next((a for a in spec if a["kind"] == "VAR_NAMED"), None)
    filled = set()
    # Run Keyword and friends: "name, *args" (not Set Suite Variable's "name, *values").
    run_variant = (norm(entry.get("owner", "")) in _RUN_VARIANT_OWNERS and var_pos is not None
                   and var_pos["name"] == "args" and positional and positional[-1]["name"] == "name")
    i = 0
    pos_i = 0
    while i < len(values):
        value = values[i]
        m = re.match(r"^([^=\s\\]+)=(.*)$", value)
        if m and not run_variant and (m.group(1) in named_ok or (var_named and not _VAR_RE.match(value))):
            name = m.group(1)
            if name in named_ok:
                cells[i]["p"] = name
                filled.add(name)
            else:
                cells[i]["p"] = "**" + var_named["name"]
            i += 1
            continue
        if pos_i < len(positional):
            param = positional[pos_i]
            cells[i]["p"] = param["name"]
            filled.add(param["name"])
            pos_i += 1
            if run_variant and param["name"] == "name" and depth < 3:
                nested = catalog.find(value)
                if nested is not None:
                    used[nested["key"]] = nested
                    cells[i]["kw"] = nested["key"]
                rest, missing_nested = label_cells(nested, values[i + 1:], catalog, used, depth + 1)
                cells[i + 1:] = rest
                missing = [a["name"] for a in positional if a["required"] and a["name"] not in filled]
                missing += [a["name"] for a in spec if a["kind"] == "NAMED_ONLY" and a["required"] and a["name"] not in filled]
                return cells, missing + missing_nested
            i += 1
            continue
        if var_pos is not None:
            cells[i]["p"] = "*" + var_pos["name"]
        else:
            cells[i]["p"] = "(extra)"
        i += 1
    missing = [a["name"] for a in positional if a["required"] and a["name"] not in filled]
    missing += [a["name"] for a in spec if a["kind"] == "NAMED_ONLY" and a["required"] and a["name"] not in filled]
    # A list variable (@{args}) may carry any number of positional values.
    if any(v.startswith("@{") for v in values):
        missing = []
    return cells, missing


_CALL_TOKENS = None


def _row(stmt, depth, catalog, used):
    from robot.api.parsing import Token
    global _CALL_TOKENS
    if _CALL_TOKENS is None:
        _CALL_TOKENS = {Token.SETUP, Token.TEARDOWN, Token.SUITE_SETUP, Token.SUITE_TEARDOWN,
                        Token.TEST_SETUP, Token.TEST_TEARDOWN, Token.TEMPLATE, Token.TEST_TEMPLATE}
    skip = {Token.SEPARATOR, Token.EOL, Token.EOS, Token.CONTINUATION, Token.COMMENT}
    tokens = [t for t in stmt.tokens if t.type not in skip]
    comment = " ".join(t.value for t in stmt.tokens if t.type == Token.COMMENT)
    row = {"line": stmt.lineno, "depth": depth, "type": stmt.type, "label": "", "assign": [],
           "keyword": None, "kw": None, "cells": [], "missing": [], "comment": comment,
           "error": getattr(stmt, "error", None) or None}
    if stmt.type == Token.KEYWORD or type(stmt).__name__ == "KeywordCall":
        row["type"] = "KEYWORD"
        row["assign"] = [t.value for t in tokens if t.type == Token.ASSIGN]
        name = stmt.keyword
        args = [t.value for t in tokens if t.type == Token.ARGUMENT]
    elif stmt.type in _CALL_TOKENS and any(t.type == Token.NAME for t in tokens):
        row["label"] = tokens[0].value
        name = next(t.value for t in tokens if t.type == Token.NAME)
        args = [t.value for t in tokens if t.type == Token.ARGUMENT]
        if name.upper() == "NONE":
            name = None
    else:
        values = [t.value for t in tokens]
        row["label"] = values[0] if values else ""
        rest = values[1:]
        if stmt.type in (Token.DOCUMENTATION,) and rest:
            # One text, however many lines it was written on.
            rest = ["\n".join(rest)]
        row["cells"] = [{"v": v, "p": None, "kw": None} for v in rest]
        return row
    row["keyword"] = name
    entry = catalog.find(name) if name else None
    if entry is not None:
        used[entry["key"]] = entry
        row["kw"] = entry["key"]
    cells, missing = label_cells(entry, args, catalog, used)
    row["cells"] = cells
    row["missing"] = missing
    return row


def _rows(nodes, depth, catalog, used):
    """Statements and blocks (FOR, IF, TRY, WHILE) as rows, blocks indented."""
    out = []
    for node in nodes or []:
        t = type(node).__name__
        if t == "EmptyLine":
            continue
        if hasattr(node, "header") and hasattr(node, "body") and t not in ("TestCase", "Keyword"):
            out.append(_row(node.header, depth, catalog, used))
            out += _rows(node.body, depth + 1, catalog, used)
            branch = getattr(node, "orelse", None) or getattr(node, "next", None)
            while branch is not None:
                out.append(_row(branch.header, depth, catalog, used))
                out += _rows(branch.body, depth + 1, catalog, used)
                branch = getattr(branch, "orelse", None) or getattr(branch, "next", None)
            end = getattr(node, "end", None)
            if end is not None:
                out.append(_row(end, depth, catalog, used))
            continue
        if hasattr(node, "tokens"):
            out.append(_row(node, depth, catalog, used))
    return out


_SECTION_TITLES = {
    "SettingSection": ("settings", "Settings"), "VariableSection": ("variables", "Variables"),
    "TestCaseSection": ("tests", "Test Cases"), "TaskSection": ("tests", "Tasks"),
    "KeywordSection": ("keywords", "Keywords"), "CommentSection": ("comments", "Comments"),
    "ImplicitCommentSection": ("comments", "Comments"),
}


def grid(model, catalog):
    used = {}
    sections = []
    for section in model.sections:
        kind, title = _SECTION_TITLES.get(type(section).__name__, ("other", type(section).__name__))
        header = getattr(section, "header", None)
        entry = {"type": kind, "title": title, "line": header.lineno if header is not None else None}
        if kind in ("tests", "keywords"):
            entry["items"] = [{"name": item.name, "line": item.lineno,
                               "rows": _rows(item.body, 0, catalog, used)}
                              for item in section.body if hasattr(item, "name") and hasattr(item, "body")]
        else:
            entry["rows"] = _rows(section.body, 0, catalog, used)
        if kind == "comments" and not any(r["comment"] or r["label"] for r in entry.get("rows", [])):
            continue
        sections.append(entry)
    return sections, used


# ------------------------------------------------------------------ editing
#
# ``python robot_grid.py --edit <path>`` with ``{"text", "edit"}`` on stdin
# applies one grid edit to the text and prints ``{"ok", "text", "line"}``
# (``line``: where the edited or new part now starts) or ``{"ok": false,
# "error"}``. Robot's own model is changed and written back, so everything
# the edit does not touch -- other lines, indentation, separators, line
# endings, comments -- stays as it was.
#
# Edits (``line`` is always where the thing starts in the text sent):
#   set          {line, row: {assign, keyword, args}}     a keyword step, or a fixture ([Setup], Suite Setup, ...)
#   insert       {after | item, row}                      a new step after a step / first step of a test or keyword
#   delete       {line}                                   a step, a setting, a variable, a whole block, or one
#                                                         ELSE IF / ELSE / EXCEPT / FINALLY branch
#   move         {line, dir: -1 | 1}                      a step or block, past its neighbour in the same body
#   header       {line, header}                           FOR {variables, flavor, values}, IF / ELSE IF {condition},
#                                                         WHILE {condition, limit}, EXCEPT {patterns, variable},
#                                                         THREAD {name, daemon} (RobotFramework AIO fork)
#   block        {after | item, block: {type, header}}    a new FOR / IF / WHILE / TRY / THREAD with a first step
#   branch       {line, branch: {type, header}}           ELSE IF / ELSE on an IF, EXCEPT / FINALLY on a TRY
#   values       {line, name?, values}                    a setting's values ([Tags], Library, Documentation, ...),
#                                                         or a variable (name and values)
#   setting      {section: "settings" | "variables", name, values}   a new setting / import / variable
#   item         {section: "tests" | "keywords", name}    a new test or keyword
#   rename       {line, name}                             a test or keyword
#   delete_item  {line}                                   a test or keyword with everything in it
#   item_setting {item, name, values}                     a test's or keyword's own [Documentation], [Tags], [Setup], ...

_ASSIGN_RE = re.compile(r"^[$@&]\{[^}]+\}\s*=?$")
_VARIABLE_NAME_RE = re.compile(r"^[$@&]\{[^}]+\}=?$")
_PLACEHOLDER = "No Operation"
_FIXTURES = ("Setup", "Teardown", "SuiteSetup", "SuiteTeardown", "TestSetup", "TestTeardown")
_SETTING_STATEMENTS = ("Documentation", "Tags", "Timeout", "Template", "Arguments", "ReturnStatement",
                       "LibraryImport", "ResourceImport", "VariablesImport", "Metadata", "ForceTags",
                       "DefaultTags", "KeywordTags", "Variable", "TestTemplate", "TestTimeout", "Return")
# The settings a grid can add, by the name written in the file.
_NEW_SETTINGS = {
    "Library": "LibraryImport", "Resource": "ResourceImport", "Variables": "VariablesImport",
    "Documentation": "Documentation", "Metadata": "Metadata",
    "Suite Setup": "SuiteSetup", "Suite Teardown": "SuiteTeardown",
    "Test Setup": "TestSetup", "Test Teardown": "TestTeardown",
    "Test Tags": "ForceTags", "Force Tags": "ForceTags", "Default Tags": "DefaultTags", "Keyword Tags": "KeywordTags",
    "Test Timeout": "TestTimeout", "Test Template": "TestTemplate",
}
_FOR_FLAVORS = ("IN", "IN RANGE", "IN ENUMERATE", "IN ZIP")
# A test's and a keyword's own settings, in the order they are written.
_TEST_SETTINGS = {"[Documentation]": "Documentation", "[Tags]": "Tags", "[Setup]": "Setup",
                  "[Template]": "Template", "[Timeout]": "Timeout", "[Teardown]": "Teardown"}
_KEYWORD_SETTINGS = {"[Documentation]": "Documentation", "[Tags]": "Tags", "[Arguments]": "Arguments",
                     "[Timeout]": "Timeout", "[Teardown]": "Teardown"}


def _item_setting(cls_name, name, values, indent, separator, eol):
    """A new [Documentation] / [Tags] / [Setup] / ... of a test or keyword."""
    from robot.parsing.model import statements as S
    if cls_name == "Documentation":
        text = "\n".join(values).strip("\n")
        if not text.strip():
            raise EditError("Write the documentation.")
        return S.Documentation.from_params(text, indent=indent, separator=separator, eol=eol, settings_section=False)
    filled = [v for v in values if v.strip()]
    if not filled:
        raise EditError(f"{name} needs a value.")
    if cls_name in ("Setup", "Teardown"):
        keyword = _clean_name(values[0], "keyword") if values and values[0].strip() else None
        if keyword is None:
            raise EditError(f"{name} needs a keyword.")
        return getattr(S, cls_name).from_params(keyword, [escape_cell(v) for v in values[1:]],
                                                indent=indent, separator=separator, eol=eol)
    if cls_name == "Arguments":
        for v in filled:
            if not re.match(r"^[$@&]\{[^}]+\}(=.*)?$", v):
                raise EditError(f"{v} is not an argument (write ${{name}}, ${{name}}=default, @{{list}} or &{{dict}}).")
        return S.Arguments.from_params(filled, indent=indent, separator=separator, eol=eol)
    if cls_name == "Tags":
        return S.Tags.from_params([escape_cell(v) for v in filled], indent=indent, separator=separator, eol=eol)
    if len(filled) > 1:
        raise EditError(f"{name} takes one value.")
    return getattr(S, cls_name).from_params(escape_cell(filled[0]), indent=indent, separator=separator, eol=eol)


class EditError(Exception):
    pass


def escape_cell(value):
    """A cell's text as Robot needs it: runs of spaces and edge spaces escaped,
    an empty value as ${EMPTY}."""
    value = str(value)
    if "\n" in value or "\r" in value or "\t" in value:
        raise EditError("A value cannot contain line breaks or tabs.")
    if value == "":
        return "${EMPTY}"
    value = re.sub(r" {2,}", lambda m: " " + "\\ " * (len(m.group(0)) - 1), value)
    if value.startswith(" "):
        value = "\\" + value
    if value.endswith(" ") and not value.endswith("\\ "):
        value = value[:-1] + "\\ "
    return value


def _clean_name(name, what):
    name = str(name or "").strip()
    if not name:
        raise EditError(f"Give the {what} a name.")
    if re.search(r"\s{2,}|\t|\n", name):
        raise EditError(f"A {what} name cannot contain two spaces in a row, tabs or line breaks.")
    return name


def _clean_row(row):
    if not isinstance(row, dict):
        raise EditError("The step is missing.")
    keyword = str(row.get("keyword") or "").strip()
    if not keyword:
        raise EditError("Choose a keyword.")
    if re.search(r"\s{2,}|\t", keyword):
        raise EditError("A keyword name cannot contain two spaces in a row.")
    assign = []
    for a in row.get("assign") or []:
        a = str(a).strip()
        if not a:
            continue
        if not _ASSIGN_RE.match(a):
            raise EditError(f"{a} is not a variable to assign to (write ${{name}}).")
        assign.append(a if a.endswith("=") else a + "=")
    args = [escape_cell(v) for v in row.get("args") or []]
    return keyword, assign, args


def _children(node):
    """(body list, index, child) directly under ``node``, and under its branches."""
    body = getattr(node, "body", None)
    if isinstance(body, list):
        for i, child in enumerate(body):
            yield body, i, child
    for attr in ("orelse", "next"):
        branch = getattr(node, attr, None)
        if branch is not None:
            yield from _children(branch)


def _walk(node):
    for body, i, child in _children(node):
        yield body, i, child
        yield from _walk(child)


def _find(model, line):
    """(body, index, node, item) of the step or block starting on ``line``;
    a block's END finds the block."""
    for section in model.sections:
        for item in getattr(section, "body", []):
            for body, i, node in _walk(item):
                end = getattr(node, "end", None)
                start = node.header.lineno if hasattr(node, "header") and hasattr(node, "body") else getattr(node, "lineno", None)
                if start == line or (end is not None and end.lineno == line):
                    return body, i, node, item
    return None


def _find_statement(model, line):
    """(body, index, statement) of a section-level statement (a setting, a variable) on ``line``."""
    for section in model.sections:
        body = getattr(section, "body", [])
        for i, node in enumerate(body):
            if not hasattr(node, "body") and getattr(node, "lineno", None) == line:
                return body, i, node
    return None


def _find_branch(model, line):
    """(owner, branch) where ``branch`` (ELSE IF / ELSE / EXCEPT / FINALLY) starts on ``line``
    and ``owner`` is what links to it (its ``orelse`` / ``next``)."""
    for section in model.sections:
        for item in getattr(section, "body", []):
            for _body, _i, node in _walk(item):
                owner = node
                while owner is not None:
                    link = "orelse" if hasattr(owner, "orelse") else "next" if hasattr(owner, "next") else None
                    branch = getattr(owner, link, None) if link else None
                    if branch is not None and branch.header.lineno == line:
                        return owner, link, branch
                    owner = branch
    return None


def _find_item(model, line):
    for section in model.sections:
        body = getattr(section, "body", [])
        for i, item in enumerate(body):
            if type(item).__name__ in ("TestCase", "Keyword") and item.lineno == line:
                return section, body, i, item
    return None


def _layout_of(node, fallback_indent="    "):
    """(indent, separator, eol) of an existing statement or block, to write a new one alike."""
    from robot.api.parsing import Token
    if node is None:
        return fallback_indent, "    ", "\n"
    if hasattr(node, "header") and hasattr(node, "body"):
        node = node.header
    tokens = getattr(node, "tokens", None) or []
    indent = tokens[0].value if tokens and tokens[0].type == Token.SEPARATOR else fallback_indent
    seps = [t.value for t in tokens[1:] if t.type == Token.SEPARATOR]
    separator = seps[0] if seps else "    "
    eol = next((t.value for t in tokens if t.type == Token.EOL and t.value.strip("\r\n") == ""), "\n") or "\n"
    if "|" in indent or "|" in separator:
        raise EditError("Pipe-separated files are not edited in the grid; use Script.")
    return indent, separator, eol


def _step_indent(indent):
    return indent + ("    " if "\t" not in indent else "\t")


def _call(keyword, assign, args, indent, separator, eol, comment=None):
    from robot.api.parsing import KeywordCall, Token
    call = KeywordCall.from_params(keyword, assign=tuple(assign), args=tuple(args),
                                   indent=indent, separator=separator, eol=eol)
    return _with_comment(call, comment, separator)


def _with_comment(statement, comment, separator):
    """``statement`` with the trailing comment the one it replaces had."""
    from robot.api.parsing import Token
    if not comment:
        return statement
    tokens = list(statement.tokens)
    tokens[-1:-1] = [Token(Token.SEPARATOR, separator), Token(Token.COMMENT, comment)]
    return type(statement)(tokens)


def _comment_of(node):
    from robot.api.parsing import Token
    return " ".join(t.value for t in getattr(node, "tokens", ()) if t.type == Token.COMMENT) or None


def _end_line(node):
    """The last line ``node`` (a statement or a block) takes."""
    last = getattr(node, "end_lineno", None)
    if last:
        return last
    return getattr(node, "lineno", 0)


def _header(kind, header, indent, separator, eol):
    """A FOR / IF / ELSE IF / ELSE / WHILE / TRY / EXCEPT / FINALLY header statement."""
    from robot.parsing.model import statements as S
    header = header or {}
    if kind == "FOR":
        variables = [str(v).strip() for v in header.get("variables") or [] if str(v).strip()]
        if not variables:
            raise EditError("A FOR loop needs a loop variable (${item}).")
        for v in variables:
            if not re.match(r"^\$\{[^}]+\}$", v):
                raise EditError(f"{v} is not a loop variable (write ${{name}}).")
        flavor = str(header.get("flavor") or "IN").upper()
        if flavor not in _FOR_FLAVORS:
            raise EditError(f"A FOR loop runs {', '.join(_FOR_FLAVORS)}, not {flavor}.")
        values = [escape_cell(v) for v in header.get("values") or [] if str(v) != ""]
        if not values:
            raise EditError("A FOR loop needs something to loop over.")
        return S.ForHeader.from_params(variables, values, flavor=flavor, indent=indent, separator=separator, eol=eol)
    if kind in ("IF", "ELSE IF", "WHILE"):
        condition = str(header.get("condition") or "").strip()
        if not condition:
            raise EditError(f"{kind} needs a condition.")
        if "\n" in condition or "\t" in condition or re.search(r" {2,}", condition):
            raise EditError("A condition is one cell: no tabs, line breaks or two spaces in a row.")
        if kind == "IF":
            return S.IfHeader.from_params(condition, indent=indent, separator=separator, eol=eol)
        if kind == "ELSE IF":
            return S.ElseIfHeader.from_params(condition, indent=indent, separator=separator, eol=eol)
        limit = str(header.get("limit") or "").strip() or None
        return S.WhileHeader.from_params(condition, limit=limit, indent=indent, separator=separator, eol=eol)
    if kind == "ELSE":
        return S.ElseHeader.from_params(indent=indent, eol=eol)
    if kind == "TRY":
        return S.TryHeader.from_params(indent=indent, eol=eol)
    if kind == "EXCEPT":
        patterns = [escape_cell(p) for p in header.get("patterns") or [] if str(p) != ""]
        variable = str(header.get("variable") or "").strip() or None
        if variable and not re.match(r"^\$\{[^}]+\}$", variable):
            raise EditError(f"{variable} is not a variable for the error (write ${{name}}).")
        kind_type = str(header.get("type") or "").strip() or None
        return S.ExceptHeader.from_params(patterns, type=kind_type, variable=variable, indent=indent,
                                          separator=separator, eol=eol)
    if kind == "FINALLY":
        return S.FinallyHeader.from_params(indent=indent, eol=eol)
    if kind == "THREAD":
        if not has_threads():
            raise EditError("THREAD needs the RobotFramework AIO fork on the project's path (Run settings).")
        name = str(header.get("name") or "").strip()
        if not name or re.search(r"\s{2,}|\t|\n", name):
            raise EditError("A thread needs a name (no tabs or two spaces in a row).")
        daemon = str(header.get("daemon") if header.get("daemon") is not None else "True").strip()
        if daemon.lower() not in ("true", "false", "yes", "no", "1", "0"):
            raise EditError("A thread's daemon setting is True (stops with its test) or False (runs on to the end of the suite).")
        return S.ThreadHeader.from_params(escape_cell(name), daemon, indent=indent, separator=separator, eol=eol)
    raise EditError(f"Unknown block {kind!r}.")


def has_threads():
    """Whether this Robot knows THREAD blocks (the RobotFramework AIO fork does, stock Robot does not)."""
    try:
        from robot.parsing.model import blocks as B
        from robot.parsing.model import statements as S
    except ImportError:
        return False
    return hasattr(B, "Thread") and hasattr(S, "ThreadHeader")


def _new_block(block, indent, separator, eol):
    """A FOR / IF / WHILE / TRY / THREAD with one placeholder step (Robot refuses empty blocks)."""
    from robot.parsing.model import blocks as B
    from robot.parsing.model.statements import End
    kind = str((block or {}).get("type") or "").upper()
    inner = _step_indent(indent)
    step = lambda: _call(_PLACEHOLDER, (), (), inner, separator, eol)   # noqa: E731
    header = _header(kind, (block or {}).get("header"), indent, separator, eol)
    end = End.from_params(indent=indent, eol=eol)
    if kind == "FOR":
        return B.For(header, [step()], end)
    if kind == "IF":
        return B.If(header, [step()], None, end)
    if kind == "WHILE":
        return B.While(header, [step()], end)
    if kind == "TRY":
        except_ = B.Try(_header("EXCEPT", {}, indent, separator, eol), [step()])
        return B.Try(header, [step()], except_, end)
    if kind == "THREAD":
        return B.Thread(header, [step()], end)
    raise EditError(f"A new block is FOR, IF, WHILE, TRY or THREAD, not {kind!r}.")


def _insert_point(model, edit):
    """(body, index, indent, separator, eol, line) where a new step or block goes:
    ``after`` a step, first in an ``item``, or last ``into`` a block or branch
    (the line of its FOR / IF / ELSE / TRY / EXCEPT / THREAD ... row)."""
    if edit.get("into") is not None:
        line = int(edit["into"])
        branch = _find_branch(model, line)
        if branch is not None:
            part = branch[2]
        else:
            found = _find(model, line)
            part = found[2] if found is not None else None
            if part is None:
                raise EditError(f"Nothing starts on line {line} any more; the text changed.")
            if not (hasattr(part, "header") and hasattr(part, "body")) or part.header.lineno != line:
                raise EditError(f"Line {line} is a step, not a FOR, IF, WHILE, TRY or THREAD to put steps into.")
        steps = [n for n in part.body if type(n).__name__ not in ("EmptyLine", "Comment")]
        if steps:
            indent, separator, eol = _layout_of(steps[-1])
        else:
            h_indent, separator, eol = _layout_of(part.header)
            indent = _step_indent(h_indent)
        at = len(part.body)
        while at > 0 and type(part.body[at - 1]).__name__ == "EmptyLine":
            at -= 1
        prev = part.body[at - 1] if at else part.header
        return part.body, at, indent, separator, eol, _end_line(prev) + 1
    if edit.get("after") is not None:
        found = _find(model, int(edit["after"]))
        if found is None:
            raise EditError(f"No step on line {edit['after']} any more; the text changed.")
        body, i, node, _item = found
        indent, separator, eol = _layout_of(node)
        return body, i + 1, indent, separator, eol, _end_line(node) + 1
    if edit.get("item") is not None:
        found = _find_item(model, int(edit["item"]))
        if found is None:
            raise EditError(f"No test or keyword on line {edit['item']} any more; the text changed.")
        item = found[3]
        first = next((n for n in item.body if type(n).__name__ not in ("EmptyLine", "Comment")), None)
        indent, separator, eol = _layout_of(first)
        # After its settings ([Documentation], [Arguments], ...), before its first step.
        at = 0
        for k, n in enumerate(item.body):
            if type(n).__name__ in ("Documentation", "Arguments", "Tags", "Setup", "Template", "Timeout"):
                at = k + 1
        prev = item.body[at - 1] if at else item.header
        return item.body, at, indent, separator, eol, _end_line(prev) + 1
    raise EditError("Say where it goes.")


def _generic(node_type, label, values, indent, separator, eol, comment=None):
    """A setting-like statement from its label and values (tokens written as given)."""
    from robot.api.parsing import Token
    from robot.parsing.model import statements as S
    cls = getattr(S, node_type)
    tokens = []
    if indent:
        tokens.append(Token(Token.SEPARATOR, indent))
    tokens.append(Token(Token.NAME if node_type == "Variable" else Token.ARGUMENT, label))
    for v in values:
        tokens += [Token(Token.SEPARATOR, separator), Token(Token.ARGUMENT, v)]
    if comment:
        tokens += [Token(Token.SEPARATOR, separator), Token(Token.COMMENT, comment)]
    tokens.append(Token(Token.EOL, eol))
    return cls(tokens)


def _setting(node, edit, eol_default):
    """A setting, an import or a variable, with new values (and a variable's new name)."""
    from robot.api.parsing import Token
    from robot.parsing.model import statements as S
    t = type(node).__name__
    indent, separator, eol = _layout_of(node, "")
    eol = eol or eol_default
    comment = _comment_of(node)
    values = [str(v) for v in edit.get("values") or []]
    if t == "Documentation":
        text = "\n".join(values).strip("\n")
        doc = S.Documentation.from_params(text, indent=indent, separator=separator, eol=eol,
                                          settings_section=not indent)
        return _with_comment(doc, comment, separator)
    if t == "Variable":
        name = str(edit.get("name") or node.name or "").strip()
        if not _VARIABLE_NAME_RE.match(name):
            raise EditError(f"{name} is not a variable name (write ${{name}}, @{{list}} or &{{dict}}).")
        return _generic("Variable", name, [escape_cell(v) for v in values] or ["${EMPTY}"], indent, separator, eol, comment)
    if t not in _SETTING_STATEMENTS:
        raise EditError("This row is not edited in the grid; change it in Script.")
    label = next((tok.value for tok in node.tokens if tok.type not in (Token.SEPARATOR, Token.EOL, Token.EOS)), "")
    if t in ("LibraryImport", "ResourceImport", "VariablesImport") and not [v for v in values if v.strip()]:
        raise EditError("An import needs a name.")
    return _generic(t, label, [escape_cell(v) for v in values], indent, separator, eol, comment)


def _section(model, kind, create=True):
    """The Settings / Variables / Test Cases / Keywords section, created when missing."""
    from robot.api.parsing import Token
    from robot.parsing.model import blocks as B
    from robot.parsing.model.statements import SectionHeader, EmptyLine
    classes = {"settings": ("SettingSection", Token.SETTING_HEADER), "variables": ("VariableSection", Token.VARIABLE_HEADER),
               "tests": ("TestCaseSection", Token.TESTCASE_HEADER), "keywords": ("KeywordSection", Token.KEYWORD_HEADER)}
    if kind not in classes:
        raise EditError(f"No section {kind!r}.")
    cls_name, header_type = classes[kind]
    for section in model.sections:
        if type(section).__name__ == cls_name:
            return section
    if not create:
        return None
    section = getattr(B, cls_name)(SectionHeader.from_params(header_type), [])
    order = ["settings", "variables", "tests", "keywords"]
    at = len(model.sections)
    for i, s in enumerate(model.sections):
        name = {v[0]: k for k, v in classes.items()}.get(type(s).__name__)
        if name in order and order.index(name) > order.index(kind):
            at = i
            break
    # A blank line after the previous section.
    if at > 0:
        prev = model.sections[at - 1]
        last = prev.body[-1] if prev.body else None
        while last is not None and hasattr(last, "body") and last.body:
            last = last.body[-1]
        if last is not None and type(last).__name__ != "EmptyLine":
            (prev.body[-1].body if hasattr(prev.body[-1], "body") else prev.body).append(EmptyLine.from_params())
    if at < len(model.sections):
        section.body.append(EmptyLine.from_params())      # a blank line before the next section
    model.sections.insert(at, section)
    return section


def _append(body, statement):
    """Append before the blank lines that close a body; the index it went to."""
    at = len(body)
    while at > 0 and type(body[at - 1]).__name__ == "EmptyLine":
        at -= 1
    body.insert(at, statement)
    return at


def apply_edit(text, edit):
    import io
    from robot.api.parsing import get_model, get_resource_model
    from robot.parsing.model import blocks as B
    from robot.parsing.model import statements as S
    path = edit.get("_path", "")
    model = (get_resource_model if path.lower().endswith(".resource") else get_model)(text)
    eol_default = "\r\n" if "\r\n" in text else "\n"
    op = edit.get("op")
    new_line = None

    def found_or_fail(line):
        found = _find(model, int(line or 0))
        if found is None:
            raise EditError(f"Nothing starts on line {line} any more; the text changed.")
        return found

    if op == "set":
        line = int(edit.get("line") or 0)
        found = _find(model, line)
        stmt = found and found[2]
        if found is None:
            sect = _find_statement(model, line)
            if sect is None:
                raise EditError(f"No step on line {line} any more; the text changed.")
            body, i, stmt = sect
        else:
            body, i = found[0], found[1]
        t = type(stmt).__name__
        keyword, assign, args = _clean_row(edit.get("row"))
        indent, separator, eol = _layout_of(stmt, "")
        comment = _comment_of(stmt)
        if t == "KeywordCall":
            body[i] = _call(keyword, assign, args, indent or "    ", separator, eol or eol_default, comment)
        elif t in _FIXTURES:
            if assign:
                raise EditError("A setup or teardown cannot assign a variable.")
            cls = getattr(S, t)
            kwargs = {"separator": separator, "eol": eol or eol_default}
            if t in ("Setup", "Teardown"):
                kwargs["indent"] = indent
            body[i] = _with_comment(cls.from_params(keyword, args, **kwargs), comment, separator)
        else:
            raise EditError("Only keyword steps and setups / teardowns are changed this way.")
        new_line = line

    elif op == "insert":
        keyword, assign, args = _clean_row(edit.get("row"))
        body, at, indent, separator, eol, new_line = _insert_point(model, edit)
        body.insert(at, _call(keyword, assign, args, indent, separator, eol or eol_default))

    elif op == "block":
        body, at, indent, separator, eol, new_line = _insert_point(model, edit)
        body.insert(at, _new_block(edit.get("block"), indent, separator, eol or eol_default))

    elif op == "delete":
        line = int(edit.get("line") or 0)
        branch = _find_branch(model, line)
        if branch is not None:
            owner, link, br = branch
            setattr(owner, link, getattr(br, link, None))
            new_line = line
        else:
            found = _find(model, line)
            if found is not None:
                body, i, node, _item = found
                if type(node).__name__ == "End" or (getattr(node, "end", None) is not None and node.end.lineno == line
                                                    and getattr(node, "lineno", None) != line):
                    raise EditError("Delete the block from its first row.")
                del body[i]
            else:
                sect = _find_statement(model, line)
                if sect is None:
                    raise EditError(f"Nothing starts on line {line} any more; the text changed.")
                body, i, stmt = sect
                if type(stmt).__name__ == "SectionHeader":
                    raise EditError("Sections are removed in Script.")
                del body[i]
            new_line = line

    elif op == "move":
        body, i, node, _item = found_or_fail(edit.get("line"))
        step = -1 if int(edit.get("dir") or 0) < 0 else 1
        j = i + step
        while 0 <= j < len(body) and type(body[j]).__name__ in ("EmptyLine",):
            j += step
        movable = lambda n: type(n).__name__ not in ("Documentation", "Arguments", "Tags", "Setup", "Teardown",  # noqa: E731
                                                     "Template", "Timeout", "EmptyLine")
        if not (0 <= j < len(body)) or not movable(body[j]):
            raise EditError("It is already the " + ("first" if step < 0 else "last") + " step here.")
        other = body[j]
        body[i], body[j] = other, node
        if step < 0:
            new_line = getattr(other, "lineno", None) or other.header.lineno
        else:
            new_line = int(edit.get("line")) + (_end_line(other) - (getattr(other, "lineno", None) or other.header.lineno) + 1)

    elif op == "header":
        line = int(edit.get("line") or 0)
        header = edit.get("header") or {}
        branch = _find_branch(model, line)
        if branch is not None:
            owner, link, br = branch
            kind = br.header.type
            indent, separator, eol = _layout_of(br.header)
            br.header = _header(kind, header, indent, separator, eol or eol_default)
        else:
            body, i, node, _item = found_or_fail(line)
            if not (hasattr(node, "header") and hasattr(node, "body")) or node.header.lineno != line:
                raise EditError("Only FOR, IF, ELSE IF, WHILE and EXCEPT rows have a header to change.")
            kind = node.header.type
            indent, separator, eol = _layout_of(node.header)
            node.header = _header(kind, header, indent, separator, eol or eol_default)
        new_line = line

    elif op == "branch":
        line = int(edit.get("line") or 0)
        body, i, node, _item = found_or_fail(line)
        spec = edit.get("branch") or {}
        kind = str(spec.get("type") or "").upper()
        indent, separator, eol = _layout_of(node.header)
        eol = eol or eol_default
        inner = _step_indent(indent)
        step = _call(_PLACEHOLDER, (), (), inner, separator, eol)
        if type(node).__name__ == "If" and kind in ("ELSE IF", "ELSE"):
            new = B.If(_header(kind, spec.get("header"), indent, separator, eol), [step])
            owner = node
            while owner.orelse is not None and owner.orelse.header.type != "ELSE":
                owner = owner.orelse
            if kind == "ELSE":
                if owner.orelse is not None:
                    raise EditError("This IF has an ELSE already.")
                owner.orelse = new
            else:
                new.orelse = owner.orelse
                owner.orelse = new
            prev = owner
        elif type(node).__name__ == "Try" and kind in ("EXCEPT", "FINALLY"):
            new = B.Try(_header(kind, spec.get("header"), indent, separator, eol), [step])
            owner = node
            while owner.next is not None and (kind == "FINALLY" or owner.next.header.type == "EXCEPT"):
                owner = owner.next
            if kind == "FINALLY" and owner.header.type == "FINALLY":
                raise EditError("This TRY has a FINALLY already.")
            new.next = owner.next
            owner.next = new
            prev = owner
        else:
            raise EditError("ELSE IF / ELSE go on an IF, EXCEPT / FINALLY on a TRY.")
        # The new branch follows the last line of the one before it.
        last = prev.body[-1] if prev.body else prev.header
        new_line = _end_line(last) + 1

    elif op == "values":
        line = int(edit.get("line") or 0)
        found = _find(model, line)
        if found is not None and type(found[2]).__name__ in _SETTING_STATEMENTS:
            body, i, stmt = found[0], found[1], found[2]
        else:
            sect = _find_statement(model, line)
            if sect is None:
                raise EditError(f"No setting on line {line} any more; the text changed.")
            body, i, stmt = sect
        body[i] = _setting(stmt, edit, eol_default)
        new_line = line

    elif op == "setting":
        kind = edit.get("section")
        name = str(edit.get("name") or "").strip()
        values = [str(v) for v in edit.get("values") or []]
        section = _section(model, kind)
        eol = eol_default
        if kind == "variables":
            if not _VARIABLE_NAME_RE.match(name):
                raise EditError(f"{name or 'The name'} is not a variable name (write ${{name}}, @{{list}} or &{{dict}}).")
            stmt = _generic("Variable", name, [escape_cell(v) for v in values] or ["${EMPTY}"], "", "    ", eol)
        else:
            t = _NEW_SETTINGS.get(name)
            if t is None:
                raise EditError(f"{name or 'That'} is not a setting the grid adds.")
            if t in ("LibraryImport", "ResourceImport", "VariablesImport", "SuiteSetup", "SuiteTeardown",
                     "TestSetup", "TestTeardown") and not [v for v in values if v.strip()]:
                raise EditError(f"{name} needs a value.")
            if t == "Documentation":
                stmt = S.Documentation.from_params("\n".join(values), indent="", separator="    ", eol=eol)
            else:
                stmt = _generic(t, name, [escape_cell(v) for v in values], "", "    ", eol)
        at = _append(section.body, stmt)
        prev = section.body[at - 1] if at else section.header
        new_line = (_end_line(prev) if prev is not None else 0) + 1

    elif op == "item":
        kind = edit.get("section")
        if kind not in ("tests", "keywords"):
            raise EditError("A new item is a test or a keyword.")
        name = _clean_name(edit.get("name"), "test" if kind == "tests" else "keyword")
        section = _section(model, kind)
        items = [n for n in section.body if type(n).__name__ in ("TestCase", "Keyword")]
        if any(norm(n.name) == norm(name) for n in items):
            raise EditError(f"There is a {'test' if kind == 'tests' else 'keyword'} called {name} already.")
        header_cls = S.TestCaseName if kind == "tests" else S.KeywordName
        item_cls = B.TestCase if kind == "tests" else B.Keyword
        indent = "    "
        if items:
            layout = next((n for n in items[-1].body if type(n).__name__ not in ("EmptyLine", "Comment")), None)
            indent, separator, _eol = _layout_of(layout)
            # A blank line between the last item and the new one.
            if not items[-1].body or type(items[-1].body[-1]).__name__ != "EmptyLine":
                items[-1].body.append(S.EmptyLine.from_params(eol=eol_default))
        new = item_cls(header_cls.from_params(name, eol=eol_default),
                       [_call(_PLACEHOLDER, (), (), indent, "    ", eol_default)])
        if model.sections[-1] is not section:
            new.body.append(S.EmptyLine.from_params(eol=eol_default))   # before the next section
        section.body.append(new)
        before = section.body[-2] if len(section.body) > 1 else section.header
        new_line = _end_line(before) + 1

    elif op == "item_setting":
        found = _find_item(model, int(edit.get("item") or 0))
        if found is None:
            raise EditError(f"No test or keyword on line {edit.get('item')} any more; the text changed.")
        _section_, _body, _i, item = found
        is_test = type(item).__name__ == "TestCase"
        allowed = _TEST_SETTINGS if is_test else _KEYWORD_SETTINGS
        name = str(edit.get("name") or "").strip()
        cls_name = allowed.get(name)
        if cls_name is None:
            raise EditError(f"{name or 'That'} is not a setting of a {'test' if is_test else 'keyword'} "
                            f"({', '.join(allowed)}).")
        if any(type(n).__name__ == cls_name for n in item.body):
            raise EditError(f"It has {name} already; click that row to change it.")
        first = next((n for n in item.body if type(n).__name__ not in ("EmptyLine", "Comment")), None)
        indent, separator, eol = _layout_of(first)
        eol = eol or eol_default
        stmt = _item_setting(cls_name, name, [str(v) for v in edit.get("values") or []], indent, separator, eol)
        order = list(allowed.values())
        if cls_name == "Teardown":
            # A teardown reads best where it runs: after the steps.
            at = _append(item.body, stmt)
        else:
            at = 0
            for k, n in enumerate(item.body):
                t = type(n).__name__
                if t in order and t != "Teardown" and order.index(t) <= order.index(cls_name):
                    at = k + 1
                elif t not in ("EmptyLine", "Comment") or k > at:
                    break
            item.body.insert(at, stmt)
        prev = item.body[at - 1] if at else item.header
        new_line = _end_line(prev) + 1

    elif op == "rename":
        found = _find_item(model, int(edit.get("line") or 0))
        if found is None:
            raise EditError(f"No test or keyword on line {edit.get('line')} any more; the text changed.")
        section, body, i, item = found
        kind = "test" if type(item).__name__ == "TestCase" else "keyword"
        name = _clean_name(edit.get("name"), kind)
        if any(norm(n.name) == norm(name) for n in body if n is not item and hasattr(n, "name") and type(n) is type(item)):
            raise EditError(f"There is a {kind} called {name} already.")
        _i, _s, eol = _layout_of(item.header, "")
        item.header = (S.TestCaseName if kind == "test" else S.KeywordName).from_params(name, eol=eol or eol_default)
        new_line = item.lineno

    elif op == "delete_item":
        found = _find_item(model, int(edit.get("line") or 0))
        if found is None:
            raise EditError(f"No test or keyword on line {edit.get('line')} any more; the text changed.")
        section, body, i, item = found
        del body[i]
        new_line = item.lineno

    else:
        raise EditError(f"Unknown edit {op!r}.")

    out = io.StringIO(newline="")
    model.save(out)
    result = out.getvalue()
    # Robot reads "\r\n" as "\n"; give the file back the line endings it had.
    if "\r\n" in text:
        result = result.replace("\r\n", "\n").replace("\n", "\r\n")
    return {"ok": True, "text": result, "line": new_line}


def main_edit():
    path = sys.argv[2]
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8-sig", errors="replace"))
        edit = dict(request.get("edit") or {}, _path=path)
        return apply_edit(str(request.get("text") or ""), edit)
    except EditError as exc:
        return {"ok": False, "error": str(exc)}
    except ImportError as exc:
        return {"ok": False, "missing": True, "error": f"This interpreter has no Robot Framework ({exc})."}


_BDD_PREFIX = re.compile(r"^(given|when|then|and|but)\s+", re.I)


def _flow_suite_text(flow):
    """A suite's Settings with a flow file's imports, so they resolve as in a suite."""
    imports = flow.get("imports") if isinstance(flow.get("imports"), dict) else {}
    lines = ["*** Settings ***"]
    for setting, section in (("Library", "libraries"), ("Resource", "resources"), ("Variables", "variables")):
        for item in imports.get(section) or []:
            parts = [str(p) for p in item] if isinstance(item, list) else [str(item)]
            if parts and parts[0].strip():
                lines.append("    ".join([setting] + parts))
    return "\n".join(lines) + "\n"


def define(path, text, name):
    """Where ``name`` -- a keyword as called, or an import -- is defined."""
    from robot.api.parsing import get_model, get_resource_model
    name = str(name or "").strip()
    if not name:
        return {"ok": True, "found": False}
    if path.lower().endswith(".flow.json"):
        try:
            flow = json.loads(text)
        except ValueError as exc:
            return {"ok": False, "error": f"The flow is not valid JSON: {exc}"}
        model, is_resource = get_model(_flow_suite_text(flow if isinstance(flow, dict) else {})), False
    else:
        is_resource = path.lower().endswith(".resource")
        model = (get_resource_model if is_resource else get_model)(text)
    catalog = build_catalog(model, path, is_resource)
    # An import: the resource file, or the library's source.
    for record in catalog.imports:
        if record.get("via") is None and record.get("source") and (record["name"] or "").strip() == name:
            return {"ok": True, "found": True, "source": record["source"], "line": None,
                    "name": record["name"], "owner": record["name"], "owner_type": record["type"]}
    entry = catalog.find(name) or catalog.find(_BDD_PREFIX.sub("", name))
    if not entry or not entry.get("source"):
        return {"ok": True, "found": False, "name": name}
    return {"ok": True, "found": True, "source": entry["source"], "line": entry.get("lineno"),
            "name": entry["name"], "owner": entry["owner"], "owner_type": entry["owner_type"]}


def main_define():
    path = sys.argv[2]
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig", errors="replace") or "{}")
    except ValueError as exc:
        return {"ok": False, "error": f"Bad request: {exc}"}
    try:
        return define(path, str(payload.get("text") or ""), payload.get("name"))
    except ImportError as exc:
        return {"ok": False, "missing": True, "error": f"This interpreter has no Robot Framework ({exc})."}
    except Exception as exc:  # noqa: BLE001 -- an answer, not a traceback
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--edit":
        return main_edit()
    if len(sys.argv) > 2 and sys.argv[1] == "--define":
        return main_define()
    path = sys.argv[1]
    text = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    try:
        from robot.api.parsing import get_model, get_resource_model
    except ImportError as exc:
        return {"ok": False, "missing": True,
                "error": f"This interpreter has no Robot Framework ({exc}). Point the project's Run settings at one."}
    is_resource = path.lower().endswith(".resource")
    try:
        # No curdir: the grid shows ${CURDIR} as written (imports fill it in themselves).
        model = (get_resource_model if is_resource else get_model)(text)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Robot Framework could not read the file: {exc}", "line": None}
    catalog = build_catalog(model, path, is_resource)
    sections, used = grid(model, catalog)
    # Every keyword the file can call, for choosing one (no documentation: the
    # short line is enough in a list; the used keywords come in full above).
    order = {"file": 0, "resource": 1, "library": 2}
    listing = [{"key": e["key"], "name": e["name"], "owner": e["owner"], "owner_type": e["owner_type"],
                "args": e.get("args") or [], "shortdoc": (e.get("shortdoc") or "")[:200]}
               for entries in catalog.by_name.values() for e in entries]
    listing.sort(key=lambda e: (order.get(e["owner_type"], 3), e["owner"].lower(), e["name"].lower()))
    return {"ok": True, "grid": {"sections": sections}, "catalog": catalog.count, "catalog_list": listing,
            "variables": catalog.variables,
            # What this Robot's syntax has beyond the stock one (the grid offers it only then).
            "features": {"thread": has_threads()},
            "keywords": {k: {kk: vv for kk, vv in v.items() if kk != "key"} for k, v in used.items()},
            "imports": catalog.imports}


if __name__ == "__main__":
    sys.stdout.write(json.dumps(main()))
