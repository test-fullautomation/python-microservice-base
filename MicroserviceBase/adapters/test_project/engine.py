"""Runner-neutral core for test projects.

A *test project* is a folder the Manager GUI exports services into. This
module owns everything that does not depend on the test runner:

* the manifest (``testproject.json``): which runner, where things live,
  and what each export wrote, with content hashes;
* finding a service's ``.proto`` on disk and the local files it imports;
* planning an export -- per file ``create`` / ``update`` / ``unchanged`` /
  ``modified`` / ``keep``, with diffs -- and applying it without
  clobbering local edits.

What gets generated (resources, starter suites, runner config) is the
runner adapter's business; see
:class:`MicroserviceBase.ports.test_project.TestProjectRunner`.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from ...ports.test_project import (
    PlannedFile,
    ServiceExport,
    TestProjectConflict,
    TestProjectError,
    TestProjectRunner,
)
from .robot_aio import RobotAioRunner

MANIFEST_NAME = "testproject.json"
SCHEMA_VERSION = 1
DEFAULT_CONSUL = "http://127.0.0.1:8500"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_DIFF_LINES = 400
_SKIP_DIRS = {".git", "results", "__pycache__", "node_modules", ".venv", "venv"}

# A generated resource carries its generation date; two exports of an
# unchanged API on different days must still compare equal.
_GENERATED_STAMP = re.compile(r"^\.\.\.\s+Generated:.*\n?", re.M)


# ---------------------------------------------------------------------------
# Runner registry -- the door for other test runners
# ---------------------------------------------------------------------------

_RUNNERS: Dict[str, TestProjectRunner] = {}


def register_runner(runner: TestProjectRunner) -> None:
    """Make a runner adapter available to test projects (keyed by ``runner_id``)."""
    _RUNNERS[runner.runner_id] = runner


register_runner(RobotAioRunner())


def available_runners() -> List[Dict[str, str]]:
    return [{"id": r.runner_id, "name": r.display_name} for r in _RUNNERS.values()]


def get_runner(runner_id: str) -> TestProjectRunner:
    runner = _RUNNERS.get(runner_id)
    if runner is None:
        raise TestProjectError(
            f"No adapter for test runner {runner_id!r}. "
            f"Available: {', '.join(sorted(_RUNNERS)) or 'none'}."
        )
    return runner


# ---------------------------------------------------------------------------
# Paths, names, files
# ---------------------------------------------------------------------------

def validate_name(name: str, what: str = "name") -> None:
    """Reject names that are unsafe as a path segment."""
    if not name or not _NAME_RE.match(name) or ".." in name:
        raise TestProjectError(
            f"Invalid {what} {name!r}: use letters, digits, '.', '_' or '-'."
        )


def _abs_root(root: str) -> str:
    if not root or not str(root).strip():
        raise TestProjectError("No test project folder given.")
    return os.path.abspath(os.path.expanduser(str(root).strip()))


def _safe_join(root: str, rel: str) -> str:
    """``root/rel``, refusing anything that would land outside ``root``."""
    rel = str(rel).replace("\\", "/")
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise TestProjectError(f"Not a project-relative path: {rel!r}")
    full = os.path.abspath(os.path.join(root, *rel.split("/")))
    try:
        inside = os.path.commonpath([full, root]) == root
    except ValueError:   # different drives on Windows
        inside = False
    if not inside:
        raise TestProjectError(f"Path escapes the test project: {rel!r}")
    return full


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read()


def _write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def _normalize(path: str, content: str) -> str:
    text = content.replace("\r\n", "\n")
    if path.endswith(".resource"):
        text = _GENERATED_STAMP.sub("", text)
    return text


def _digest(path: str, content: str) -> str:
    return hashlib.sha256(_normalize(path, content).encode("utf-8")).hexdigest()


def _diff(path: str, old: str, new: str) -> str:
    lines = list(difflib.unified_diff(
        old.replace("\r\n", "\n").splitlines(True),
        new.replace("\r\n", "\n").splitlines(True),
        fromfile=f"{path} (on disk)", tofile=f"{path} (new)", n=2,
    ))
    if len(lines) > _MAX_DIFF_LINES:
        extra = len(lines) - _MAX_DIFF_LINES
        lines = lines[:_MAX_DIFF_LINES] + [f"... diff truncated ({extra} more lines)\n"]
    return "".join(lines)


def _generator_version() -> str:
    try:
        from importlib.metadata import version
        return "MicroserviceBase " + version("MicroserviceBase")
    except Exception:   # noqa: BLE001 -- not installed as a distribution
        return "MicroserviceBase"


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def _project_name(root: str) -> str:
    return os.path.basename(root.rstrip("\\/")) or "tests"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _load_manifest(root: str) -> Optional[dict]:
    path = os.path.join(root, MANIFEST_NAME)
    if not os.path.isfile(path):
        return None
    try:
        data = json.loads(_read_text(path))
    except ValueError as exc:
        raise TestProjectError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from None
    if not isinstance(data, dict) or not data.get("runner"):
        raise TestProjectError(f"{MANIFEST_NAME} has no 'runner' entry.")
    if not isinstance(data.get("services"), dict):
        data["services"] = {}
    return data


def _save_manifest(root: str, data: dict) -> None:
    _write_text(os.path.join(root, MANIFEST_NAME),
                json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _layout(runner: TestProjectRunner, manifest: dict) -> Dict[str, str]:
    """Runner defaults, overridden by whatever the manifest says."""
    layout = dict(runner.default_layout())
    for key, value in (manifest.get("layout") or {}).items():
        if isinstance(value, str) and value.strip():
            layout[key] = value.strip().replace("\\", "/").strip("/")
    return layout


# ---------------------------------------------------------------------------
# Describe / init
# ---------------------------------------------------------------------------

def _detect(root: str) -> Dict[str, object]:
    suites = 0
    aio_config = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if os.path.relpath(dirpath, root).count(os.sep) >= 4:
            dirnames[:] = []
        suites += sum(1 for f in filenames if f.endswith(".robot"))
        if os.path.basename(dirpath) == "config" and "robot_config.jsonp" in filenames:
            aio_config = True
    return {"robot_suites": suites, "aio_config": aio_config}


def describe(root: str) -> dict:
    """What the GUI needs to show a folder as (or offer it as) a test project."""
    root = _abs_root(root)
    out = {
        "status": "ok",
        "root": root,
        "name": _project_name(root),
        "exists": os.path.isdir(root),
        "initialized": False,
        "runners": available_runners(),
        "services": [],
        "detected": {},
    }
    if not out["exists"]:
        return out
    out["detected"] = _detect(root)
    manifest = _load_manifest(root)
    if manifest is None:
        return out
    runner = get_runner(manifest["runner"])
    out.update(initialized=True, runner=runner.runner_id,
               runner_name=runner.display_name, layout=_layout(runner, manifest))
    for name, entry in sorted(manifest["services"].items()):
        out["services"].append({
            "name": name,
            "grpc_services": entry.get("grpc_services", []),
            "source": entry.get("source", {}),
            "exported_at": entry.get("exported_at", ""),
            "files": len(entry.get("files", {})),
        })
    return out


def init_project(root: str, runner_id: str, *, consul_addr: str = "") -> dict:
    """Turn an existing folder into a test project. Existing files are left alone."""
    root = _abs_root(root)
    if not os.path.isdir(root):
        raise TestProjectError(f"Folder does not exist: {root}")
    if _load_manifest(root) is not None:
        raise TestProjectError(f"{root} is already a test project ({MANIFEST_NAME} exists).")
    runner = get_runner(runner_id)
    layout = runner.default_layout()
    for rel in layout.values():
        os.makedirs(_safe_join(root, rel), exist_ok=True)

    created, kept = [], []
    for rel, content in runner.init_files(layout, _project_name(root),
                                          consul_addr or DEFAULT_CONSUL).items():
        full = _safe_join(root, rel)
        if os.path.exists(full):
            kept.append(rel)
            continue
        _write_text(full, content)
        created.append(rel)

    _save_manifest(root, {
        "schema": SCHEMA_VERSION,
        "runner": runner.runner_id,
        "layout": layout,
        "created_at": _now(),
        "generator": _generator_version(),
        "services": {},
    })
    result = describe(root)
    result.update(created=[MANIFEST_NAME] + created, kept=kept)
    return result


# ---------------------------------------------------------------------------
# Proto discovery
# ---------------------------------------------------------------------------

_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_PACKAGE_RE = re.compile(r"\bpackage\s+([\w.]+)\s*;")
_SERVICE_RE = re.compile(r"\bservice\s+(\w+)\s*\{")
_IMPORT_RE = re.compile(r'\bimport\s+(?:public\s+|weak\s+)?"([^"]+)"\s*;')


def proto_services(path: str) -> set:
    """Fully-qualified service names declared in a ``.proto`` (text scan)."""
    try:
        text = _COMMENT_RE.sub("", _read_text(path))
    except OSError:
        return set()
    match = _PACKAGE_RE.search(text)
    package = match.group(1) if match else ""
    return {f"{package}.{name}" if package else name for name in _SERVICE_RE.findall(text)}


def locate_service_proto(
    grpc_services: Iterable[str],
    search_paths: Iterable[str],
    *,
    is_excluded: Optional[Callable[[str], bool]] = None,
) -> Optional[str]:
    """First ``.proto`` under *search_paths* declaring **all** *grpc_services*,
    or ``None``. See :func:`find_service_protos`."""
    matches = find_service_protos(grpc_services, search_paths, is_excluded=is_excluded)
    return matches[0] if matches else None


def find_service_protos(
    grpc_services: Iterable[str],
    search_paths: Iterable[str],
    *,
    is_excluded: Optional[Callable[[str], bool]] = None,
) -> List[str]:
    """Every ``.proto`` under *search_paths* declaring **all** *grpc_services*.

    Search paths are tried in order and walked in sorted order, so the
    order is deterministic. Entries may be folders or ``.proto`` files.

    Copies of one proto are common (a service and its client examples
    each carry one), so callers should say which match they used rather
    than pretend there was only one.
    """
    wanted = {s for s in grpc_services if s}
    matches: List[str] = []
    if not wanted:
        return matches
    for base in search_paths:
        if not base:
            continue
        base = os.path.abspath(base)
        if os.path.isfile(base):
            candidates = [base] if base.endswith(".proto") else []
        elif os.path.isdir(base):
            candidates = []
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
                for fname in sorted(filenames):
                    if not fname.endswith(".proto"):
                        continue
                    full = os.path.join(dirpath, fname)
                    if is_excluded is None or not is_excluded(full):
                        candidates.append(full)
        else:
            continue
        for path in candidates:
            if path not in matches and wanted <= proto_services(path):
                matches.append(path)
    return matches


def collect_proto_set(proto_file: str) -> Tuple[Dict[str, str], List[str]]:
    """The service's ``.proto`` plus the local files it imports, transitively.

    Returns ``({relative_path: text}, warnings)`` with paths relative to the
    folder of *proto_file* -- the include root protoc sees. Google's
    well-known types ship with protoc and are not copied.
    """
    proto_file = os.path.abspath(proto_file)
    base = os.path.dirname(proto_file)
    files: Dict[str, str] = {}
    warnings: List[str] = []
    queue = [os.path.basename(proto_file)]
    while queue:
        rel = queue.pop(0).replace("\\", "/")
        if rel in files or rel.startswith("google/protobuf/"):
            continue
        if rel.startswith("/") or ".." in rel.split("/"):
            warnings.append(f"Import {rel!r} points outside the proto folder; it was not copied.")
            continue
        full = os.path.join(base, *rel.split("/"))
        if not os.path.isfile(full):
            warnings.append(
                f"Import {rel!r} was not found next to {os.path.basename(proto_file)}; "
                "it was not copied."
            )
            continue
        text = _read_text(full)
        files[rel] = text
        queue.extend(_IMPORT_RE.findall(_COMMENT_RE.sub("", text)))
    return files, warnings


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_service(
    root: str,
    consul_name: str,
    *,
    consul_addr: str,
    grpc_services: Iterable[str],
    proto_files: Optional[Dict[str, str]] = None,
    file_descriptors: Optional[list] = None,
    source: Optional[dict] = None,
    create_starter: bool = True,
    apply: bool = False,
    overwrite_modified: bool = False,
    warnings: Optional[List[str]] = None,
) -> dict:
    """Plan -- and with ``apply=True`` write -- one service's files.

    The plan is always recomputed from the inputs, so an apply never
    writes content the user did not see in an equivalent plan.

    ``proto_files`` (``{relative_path: text}``, see :func:`collect_proto_set`)
    wins over ``file_descriptors``; with protos, generation runs on exactly
    the files that get copied.
    """
    root = _abs_root(root)
    validate_name(consul_name, "service name")
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(
            f"{root} is not a test project yet -- open it in the Manager GUI "
            "and initialize it first."
        )
    runner = get_runner(manifest["runner"])
    layout = _layout(runner, manifest)
    if not proto_files and not file_descriptors:
        raise TestProjectError(
            "Nothing to generate from: no .proto file and no reflection descriptors."
        )

    notes = list(warnings or [])
    proto_rel_dir = f"{layout['proto']}/{consul_name}" if proto_files else None
    staging = tempfile.mkdtemp(prefix="mm_testproject_") if proto_files else None
    try:
        for rel, text in (proto_files or {}).items():
            _write_text(os.path.join(staging, *rel.split("/")), text)
        export = ServiceExport(
            consul_name=consul_name,
            consul_addr=consul_addr or DEFAULT_CONSUL,
            grpc_services=list(grpc_services or []),
            proto_dir=staging,
            proto_rel_dir=proto_rel_dir,
            file_descriptors=None if proto_files else file_descriptors,
            project_name=_project_name(root),
        )
        planned = list(runner.service_files(layout, export, create_starter=create_starter))
        advisories = list(runner.advisories(root, layout, export))
    except TestProjectError:
        raise
    except Exception as exc:   # noqa: BLE001 -- surface generator failures as user errors
        raise TestProjectError(f"Generation failed: {exc}") from exc
    finally:
        if staging:
            shutil.rmtree(staging, ignore_errors=True)

    for rel, text in sorted((proto_files or {}).items()):
        planned.append(PlannedFile(f"{proto_rel_dir}/{rel}", text, "generated"))
    planned.sort(key=lambda f: (f.role != "generated", f.path.startswith(f"{layout['proto']}/"), f.path))

    previous = manifest["services"].get(consul_name, {})
    prev_files = previous.get("files", {}) if isinstance(previous, dict) else {}

    rows = []
    for pf in planned:
        full = _safe_join(root, pf.path)
        row = {"path": pf.path, "role": pf.role}
        if not os.path.exists(full):
            row["status"] = "create"
        elif pf.role == "starter":
            row["status"] = "keep"
        else:
            disk = _read_text(full)
            if _normalize(pf.path, disk) == _normalize(pf.path, pf.content):
                row["status"] = "unchanged"
            else:
                recorded = (prev_files.get(pf.path) or {}).get("sha256")
                row["status"] = "update" if recorded == _digest(pf.path, disk) else "modified"
                row["diff"] = _diff(pf.path, disk, pf.content)
        rows.append((pf, row))

    produced = {pf.path for pf, _ in rows}
    stale = []
    for path, meta in sorted(prev_files.items()):
        if (meta or {}).get("role") != "generated" or path in produced:
            continue
        if os.path.exists(_safe_join(root, path)):
            stale.append(path)
            advisories.append(
                f"{path} came from an earlier export but is no longer produced "
                "(did the service API change?). It was left in place; delete it "
                "if nothing uses it."
            )

    written: List[str] = []
    skipped: List[str] = []
    if apply:
        for pf, row in rows:
            status = row["status"]
            if status in ("create", "update") or (status == "modified" and overwrite_modified):
                _write_text(_safe_join(root, pf.path), pf.content)
                written.append(pf.path)
            elif status == "modified":
                skipped.append(pf.path)

        files_meta: Dict[str, dict] = {}
        for pf, row in rows:
            if pf.role == "starter":
                files_meta[pf.path] = {"role": "starter"}
            elif pf.path in skipped:
                # Keep the previous record, so the next export still
                # recognises the file as locally edited.
                if pf.path in prev_files:
                    files_meta[pf.path] = prev_files[pf.path]
            else:
                files_meta[pf.path] = {"role": "generated", "sha256": _digest(pf.path, pf.content)}
        for path in stale:   # still on disk: keep reporting it
            files_meta[path] = prev_files[path]

        manifest["services"][consul_name] = {
            "grpc_services": export.grpc_services,
            "consul_addr": export.consul_addr,
            "source": source or {},
            "exported_at": _now(),
            "generator": _generator_version(),
            "files": files_meta,
        }
        _save_manifest(root, manifest)

    return {
        "status": "ok",
        "root": root,
        "service": consul_name,
        "runner": runner.runner_id,
        "runner_name": runner.display_name,
        "source": source or {},
        "files": [row for _, row in rows],
        "advisories": advisories,
        "warnings": notes,
        "run_hint": runner.run_hint(layout, export),
        "applied": bool(apply),
        "written": written,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Project view (read-only; never contacts a service)
# ---------------------------------------------------------------------------

_TREE_MAX_FILES = 2000
_TREE_MAX_DEPTH = 8
_PREVIEW_MAX_BYTES = 512_000

_KINDS = {
    ".robot": "suite", ".resource": "resource", ".proto": "proto",
    ".jsonp": "config", ".json": "config", ".args": "config",
    ".py": "library", ".md": "doc", ".txt": "doc",
}


def _kind(rel: str) -> str:
    return _KINDS.get(os.path.splitext(rel)[1].lower(), "other")


def _file_entry(root: str, rel: str, tracked) -> dict:
    full = os.path.join(root, *rel.split("/"))
    entry = {"path": rel, "kind": _kind(rel), "size": os.path.getsize(full), "service": None}
    if rel == MANIFEST_NAME:
        entry.update(role="manifest", state="ok")
        return entry
    if tracked is None:
        entry.update(role="yours", state="yours")
        return entry
    service, meta = tracked
    role = meta.get("role", "generated")
    state = "ok"
    if role == "generated":
        try:
            state = "ok" if meta.get("sha256") == _digest(rel, _read_text(full)) else "edited"
        except OSError:
            state = "unreadable"
    entry.update(role=role, state=state, service=service)
    return entry


def project_tree(root: str) -> dict:
    """Every file of a test project with its role and sync state.

    ``role``: ``manifest`` | ``generated`` | ``starter`` | ``yours`` (not
    written by an export). ``state`` for generated files: ``ok`` (as
    exported), ``edited`` (changed since), ``missing`` (deleted since).
    """
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    runner = get_runner(manifest["runner"])
    layout = _layout(runner, manifest)

    tracked = {}
    for service, entry in manifest["services"].items():
        for path, meta in ((entry or {}).get("files") or {}).items():
            tracked[path] = (service, meta or {})

    files: List[dict] = []
    seen = set()
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        if os.path.relpath(dirpath, root).count(os.sep) >= _TREE_MAX_DEPTH:
            dirnames[:] = []
        for fname in sorted(filenames):
            if len(files) >= _TREE_MAX_FILES:
                truncated = True
                break
            rel = os.path.relpath(os.path.join(dirpath, fname), root).replace(os.sep, "/")
            seen.add(rel)
            files.append(_file_entry(root, rel, tracked.get(rel)))
        if truncated:
            break
    if not truncated:
        for rel, (service, meta) in sorted(tracked.items()):
            if rel not in seen:
                files.append({"path": rel, "kind": _kind(rel), "size": 0, "service": service,
                              "role": meta.get("role", "generated"), "state": "missing"})

    services = []
    for name, entry in sorted(manifest["services"].items()):
        entry = entry or {}
        counts = {"ok": 0, "edited": 0, "missing": 0}
        for f in files:
            if f["service"] == name and f["state"] in counts:
                counts[f["state"]] += 1
        services.append({
            "name": name,
            "grpc_services": entry.get("grpc_services", []),
            "consul_addr": entry.get("consul_addr", ""),
            "source": entry.get("source", {}),
            "exported_at": entry.get("exported_at", ""),
            "generator": entry.get("generator", ""),
            "files": counts,
        })

    return {
        "status": "ok",
        "root": root,
        "name": _project_name(root),
        "runner": runner.runner_id,
        "runner_name": runner.display_name,
        "layout": layout,
        "services": services,
        "files": files,
        "truncated": truncated,
        "run_hint": runner.project_run_hint(layout),
    }


_EDITABLE_ROLES = ("yours", "starter")
_NEW_SUITE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _tracked_map(manifest: dict) -> Dict[str, Tuple[str, dict]]:
    tracked = {}
    for service, entry in manifest["services"].items():
        for path, meta in ((entry or {}).get("files") or {}).items():
            tracked[path] = (service, meta or {})
    return tracked


def _role_of(manifest: dict, rel: str) -> str:
    if rel == MANIFEST_NAME:
        return "manifest"
    tracked = _tracked_map(manifest).get(rel)
    return (tracked[1].get("role", "generated") if tracked else "yours")


def read_project_file(root: str, rel: str) -> dict:
    """Text content of one project file, with what is needed to edit it safely.

    ``sha256`` is the hash of the bytes on disk; pass it back to
    :func:`write_project_file` so a save can detect a concurrent change.
    ``editable`` is true for user-owned files (``yours`` / ``starter``).
    """
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    rel = str(rel).replace("\\", "/")
    full = _safe_join(root, rel)
    if not os.path.isfile(full):
        raise TestProjectError(f"No such file in the test project: {rel}")
    size = os.path.getsize(full)
    if size > _PREVIEW_MAX_BYTES:
        raise TestProjectError(
            f"{rel} is {size // 1024} KB; previews are limited to "
            f"{_PREVIEW_MAX_BYTES // 1024} KB.")
    with open(full, "rb") as fh:
        raw = fh.read()
    if b"\x00" in raw[:8192]:
        raise TestProjectError(f"{rel} looks like a binary file; there is no preview.")
    role = _role_of(manifest, rel)
    return {"status": "ok", "path": rel, "size": size, "sha256": _sha256(raw),
            "role": role, "editable": role in _EDITABLE_ROLES,
            "content": raw.decode("utf-8", errors="replace")}


def check_syntax(rel: str, content: str) -> List[dict]:
    """Robot Framework parse problems of a ``.robot`` / ``.resource`` text.

    Returns ``[{"line": n, "message": text}]``; empty when the text parses
    cleanly, when the file is not Robot data, or when Robot Framework is not
    installed. This is a syntax check -- keyword names are not resolved.
    """
    lower = str(rel).lower()
    if not lower.endswith((".robot", ".resource")):
        return []
    try:
        import io
        from robot.api import Token, get_resource_tokens, get_tokens
    except ImportError:
        return []
    tokenize = get_resource_tokens if lower.endswith(".resource") else get_tokens
    problems = []
    for token in tokenize(io.StringIO(content)):
        if token.type in (Token.ERROR, Token.FATAL_ERROR) or getattr(token, "error", None):
            problems.append({"line": token.lineno,
                             "message": token.error or f"Invalid syntax: {token.value!r}"})
    return problems


def write_project_file(root: str, rel: str, content: str, *,
                       expected_sha256: Optional[str] = None,
                       create: bool = False, force: bool = False) -> dict:
    """Save a user-owned file of a test project.

    Refuses generated files and the manifest (exports own them), paths
    outside the project, and -- unless ``force`` -- a file whose bytes on
    disk no longer match ``expected_sha256``
    (:class:`~MicroserviceBase.ports.test_project.TestProjectConflict`).
    With ``create=True`` the file must not exist and must be ``.robot`` or
    ``.resource``. Returns the new hash and any syntax problems.
    """
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    rel = str(rel).replace("\\", "/")
    full = _safe_join(root, rel)

    role = _role_of(manifest, rel)
    if role == "manifest":
        raise TestProjectError(f"{MANIFEST_NAME} is maintained by the tool and cannot be edited here.")
    if role == "generated":
        raise TestProjectError(
            f"{rel} is generated by exports and read-only here -- an edit would stop the "
            "next export from updating it. Put your keywords in a hand-written resource.")

    encoded = content.encode("utf-8")
    if len(encoded) > _PREVIEW_MAX_BYTES:
        raise TestProjectError(f"Content is larger than {_PREVIEW_MAX_BYTES // 1024} KB.")

    exists = os.path.isfile(full)
    if create:
        if os.path.exists(full):
            raise TestProjectError(f"{rel} already exists.")
        if not rel.lower().endswith((".robot", ".resource")):
            raise TestProjectError("New files must be .robot or .resource files.")
    elif not exists:
        raise TestProjectError(f"No such file in the test project: {rel}")
    elif expected_sha256 and not force:
        with open(full, "rb") as fh:
            current = _sha256(fh.read())
        if current != expected_sha256:
            raise TestProjectConflict(
                f"{rel} changed on disk since it was opened. Reload it to see the change, "
                "or overwrite it with your version.")

    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(encoded)
    return {"status": "ok", "path": rel, "size": len(encoded), "sha256": _sha256(encoded),
            "role": "yours" if create else role, "created": bool(create),
            "problems": check_syntax(rel, content)}


def create_suite(root: str, name: str, *, service: Optional[str] = None) -> dict:
    """Create a new suite in the project's suites folder from the runner's template.

    With ``service``, the suite imports that service's generated resources
    and opens (and closes) its connections.
    """
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    runner = get_runner(manifest["runner"])
    layout = _layout(runner, manifest)

    stem = re.sub(r"\.robot$", "", str(name or "").strip(), flags=re.I)
    if not _NEW_SUITE_RE.match(stem):
        raise TestProjectError(
            f"Invalid suite name {name!r}: use letters, digits, '_' or '-' (no spaces).")
    rel = f"{layout['suites']}/{stem}.robot"

    resources: List[str] = []
    consul_addr = DEFAULT_CONSUL
    proto_rel_dir = None
    if service:
        validate_name(service, "service name")
        entry = manifest["services"].get(service)
        if not entry:
            raise TestProjectError(f"{service} has not been exported into this project.")
        files = entry.get("files") or {}
        resources = sorted(p for p, m in files.items()
                           if (m or {}).get("role") == "generated" and p.endswith(".resource"))
        consul_addr = entry.get("consul_addr") or DEFAULT_CONSUL
        if (entry.get("source") or {}).get("kind") == "proto":
            proto_rel_dir = f"{layout['proto']}/{service}"

    content = runner.suite_template(layout, rel, service, resources, consul_addr, proto_rel_dir)
    if not content:
        raise TestProjectError(f"{runner.display_name} projects cannot create suites here.")
    return write_project_file(root, rel, content, create=True)
