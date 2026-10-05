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
from dataclasses import asdict
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from ...ports.test_project import (
    RUNNER_ENTRY_POINTS,
    FileType,
    GroupMember,
    PlannedFile,
    RunGroup,
    RunSettings,
    ServiceExport,
    TestProjectConflict,
    TestProjectError,
    TestProjectRunner,
)
from .robot_aio import RobotAioRunner
from .temporal import TemporalPythonRunner

MANIFEST_NAME = "testproject.json"
SCHEMA_VERSION = 1
DEFAULT_CONSUL = "http://127.0.0.1:8500"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_DIFF_LINES = 400
_SKIP_DIRS = {".git", "results", "__pycache__", "node_modules", ".venv", "venv"}

# ---------------------------------------------------------------------------
# Runner registry -- the door for other test runners
# ---------------------------------------------------------------------------

_RUNNERS: Dict[str, TestProjectRunner] = {}
_PLUGINS_LOADED = False
#: Entry points that could not be loaded: ``{name: reason}``.
PLUGIN_ERRORS: Dict[str, str] = {}


def register_runner(runner: TestProjectRunner) -> None:
    """Make a runner adapter available to test projects (keyed by ``runner_id``)."""
    if not isinstance(runner, TestProjectRunner) or not runner.runner_id:
        raise TestProjectError(f"{runner!r} is not a test runner with a runner_id.")
    _RUNNERS[runner.runner_id] = runner


register_runner(RobotAioRunner())
register_runner(TemporalPythonRunner())


def _load_plugins() -> None:
    """Runners other packages declare as entry points (``RUNNER_ENTRY_POINTS``),
    loaded once, on first use. A broken plugin is skipped and noted in
    :data:`PLUGIN_ERRORS`, never fatal; it never replaces a registered runner."""
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED:
        return
    _PLUGINS_LOADED = True
    try:
        from importlib.metadata import entry_points
        found = entry_points()
        found = (found.select(group=RUNNER_ENTRY_POINTS) if hasattr(found, "select")
                 else found.get(RUNNER_ENTRY_POINTS, []))
    except Exception as exc:   # noqa: BLE001 -- a broken environment must not stop the GUI
        PLUGIN_ERRORS["*"] = str(exc)
        return
    for ep in found:
        try:
            obj = ep.load()
            runner = obj if isinstance(obj, TestProjectRunner) else obj()
            if runner.runner_id not in _RUNNERS:
                register_runner(runner)
        except Exception as exc:   # noqa: BLE001
            PLUGIN_ERRORS[ep.name] = f"{type(exc).__name__}: {exc}"


def _runner_info(runner: TestProjectRunner) -> Dict[str, object]:
    return {"id": runner.runner_id, "name": runner.display_name,
            "description": runner.description,
            "structure": runner.structure(runner.default_layout())}


def available_runners() -> List[Dict[str, object]]:
    """Every registered runner: ``id``, ``name``, ``description`` and the
    ``structure`` of its projects, for the GUI's runner choice."""
    _load_plugins()
    return [_runner_info(r) for r in _RUNNERS.values()]


def get_runner(runner_id: str) -> TestProjectRunner:
    _load_plugins()
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


def _normalize(content: str, runner: Optional[TestProjectRunner]) -> str:
    text = content.replace("\r\n", "\n")
    # A generated file may carry its generation date; two exports of an
    # unchanged API on different days must still compare equal.
    if runner is not None and runner.generated_stamp:
        text = re.sub(runner.generated_stamp, "", text, flags=re.M)
    return text


def _digest(path: str, content: str, runner: Optional[TestProjectRunner] = None) -> str:
    return hashlib.sha256(_normalize(content, runner).encode("utf-8")).hexdigest()


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

def walk_files(root: str, max_depth: int = 4) -> Iterable[Tuple[str, List[str]]]:
    """``(dirpath, filenames)`` of a folder, at most ``max_depth`` deep,
    skipping results, caches and virtual environments -- for runners'
    :meth:`~MicroserviceBase.ports.test_project.TestProjectRunner.detect`."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if os.path.relpath(dirpath, root).count(os.sep) >= max_depth:
            dirnames[:] = []
        yield dirpath, filenames


def _detect(root: str) -> Dict[str, Dict[str, object]]:
    """What each runner recognises in the folder: ``{runner_id: {"count", "summary"}}``."""
    found = {}
    for runner in list(_RUNNERS.values()):
        try:
            info = runner.detect(root) or {}
        except Exception as exc:   # noqa: BLE001 -- one runner's bug must not hide the others
            info = {"error": str(exc)}
        if info:
            found[runner.runner_id] = info
    return found


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
        "default_runner": RobotAioRunner.runner_id,
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
            if _normalize(disk, runner) == _normalize(pf.content, runner):
                row["status"] = "unchanged"
            else:
                recorded = (prev_files.get(pf.path) or {}).get("sha256")
                row["status"] = "update" if recorded == _digest(pf.path, disk, runner) else "modified"
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
                files_meta[pf.path] = {"role": "generated", "sha256": _digest(pf.path, pf.content, runner)}
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

# Kinds of files any project may hold, whatever its runner; the runner's
# own file types (FileType) are asked first.
_KINDS = {
    ".proto": "proto", ".jsonp": "config", ".json": "config", ".toml": "config",
    ".ini": "config", ".cfg": "config", ".yaml": "config", ".yml": "config", ".args": "config",
    ".py": "library", ".md": "doc", ".txt": "doc",
}

# The GUI's group titles when the runner gives none.
_KIND_TITLES = {"suite": "Suites", "flow": "Flows", "resource": "Resources", "proto": "Protos",
                "config": "Configuration", "library": "Libraries", "doc": "Documents",
                "other": "Other files"}


def _kind(rel: str, runner: Optional[TestProjectRunner] = None,
          layout: Optional[Dict[str, str]] = None) -> str:
    if runner is not None:
        kind = runner.file_kind(layout or runner.default_layout(), rel)
        if kind:
            return kind
    return _KINDS.get(os.path.splitext(rel)[1].lower(), "other")


def _file_type(runner: TestProjectRunner, kind: str) -> Optional[FileType]:
    return next((ft for ft in runner.file_types() if ft.kind == kind), None)


def _kinds_info(runner: TestProjectRunner) -> List[Dict[str, object]]:
    """The project's file groups for the GUI: the runner's kinds first, in
    its order, then the generic ones."""
    out, seen = [], set()
    for ft in runner.file_types():
        if ft.kind in seen:
            continue
        seen.add(ft.kind)
        out.append({"kind": ft.kind, "title": ft.title or _KIND_TITLES.get(ft.kind, ft.kind.title()),
                    "noun": ft.noun or ft.kind, "suffix": ft.suffix, "folder": ft.folder,
                    "creatable": ft.creatable})
    for kind in ("proto", "config", "library", "doc", "other"):
        if kind not in seen:
            out.append({"kind": kind, "title": _KIND_TITLES[kind], "noun": kind, "suffix": "",
                        "folder": "", "creatable": False})
    return out


def _can_create(runner: TestProjectRunner, layout: Dict[str, str], kind: str) -> bool:
    """The runner has a creatable file type ``kind`` and a template for it."""
    ft = _file_type(runner, kind)
    if ft is None or not ft.creatable:
        return False
    folder = layout.get(ft.folder) or ft.folder or "."
    rel = f"{folder}/new{ft.suffix}"
    if kind == "flow":
        return bool(runner.flow_template(layout, rel, "New", []))
    return bool(runner.suite_template(layout, rel, None, [], DEFAULT_CONSUL, None))


def _file_entry(root: str, rel: str, tracked, runner: Optional[TestProjectRunner] = None,
                layout: Optional[Dict[str, str]] = None) -> dict:
    full = os.path.join(root, *rel.split("/"))
    own = bool(runner and rel != MANIFEST_NAME)
    runnable = bool(own and runner.can_run(rel))
    entry = {"path": rel, "kind": "config" if rel == MANIFEST_NAME else _kind(rel, runner, layout),
             "size": os.path.getsize(full), "service": None, "runnable": runnable,
             "run_hint": (runner.file_run_hint(layout or runner.default_layout(), rel)
                          if runnable else ""),
             "views": runner.file_views(rel) if own else []}
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
            state = "ok" if meta.get("sha256") == _digest(rel, _read_text(full), runner) else "edited"
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
            files.append(_file_entry(root, rel, tracked.get(rel), runner, layout))
        if truncated:
            break
    if not truncated:
        for rel, (service, meta) in sorted(tracked.items()):
            if rel not in seen:
                files.append({"path": rel, "kind": _kind(rel, runner, layout), "size": 0,
                              "service": service, "runnable": False, "run_hint": "", "views": [],
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
        "can_run": runner.can_run(""),
        "can_debug": runner.can_debug(""),
        "can_new_suite": _can_create(runner, layout, "suite"),
        "can_new_flow": _can_create(runner, layout, "flow"),
        "kinds": _kinds_info(runner),
        "run_settings": asdict(run_settings_of(manifest)),
        "groups": [_group_entry(runner, g) for g in groups_of(manifest)],
    }


# ---------------------------------------------------------------------------
# Run settings (``"run"`` in the manifest)
# ---------------------------------------------------------------------------

def run_settings_of(manifest: dict) -> RunSettings:
    raw = manifest.get("run") if isinstance(manifest.get("run"), dict) else {}

    def strings(value) -> List[str]:
        return [str(v) for v in value] if isinstance(value, list) else []

    env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    return RunSettings(python=str(raw.get("python") or ""),
                       pythonpath=strings(raw.get("pythonpath")),
                       args=strings(raw.get("args")),
                       env={str(k): str(v) for k, v in env.items()})


def get_run_settings(root: str) -> dict:
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    return {"status": "ok", "root": root, "settings": asdict(run_settings_of(manifest))}


def set_run_settings(root: str, settings: dict) -> dict:
    """Replace the project's run settings; unknown keys are refused."""
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    if not isinstance(settings, dict):
        raise TestProjectError("Run settings must be an object.")
    unknown = set(settings) - {"python", "pythonpath", "args", "env"}
    if unknown:
        raise TestProjectError(f"Unknown run settings: {', '.join(sorted(unknown))}")
    for key in ("pythonpath", "args"):
        value = settings.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise TestProjectError(f"'{key}' must be a list of strings.")
    if not isinstance(settings.get("python", ""), str):
        raise TestProjectError("'python' must be a string.")
    env = settings.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise TestProjectError("'env' must map names to strings.")
    clean = RunSettings(python=settings.get("python", "").strip(),
                        pythonpath=[p.strip() for p in settings.get("pythonpath", []) if p.strip()],
                        args=[a for a in settings.get("args", []) if a.strip()],
                        env={k.strip(): v for k, v in env.items() if k.strip()})
    data = asdict(clean)
    if any(data.values()):
        manifest["run"] = data
    else:
        manifest.pop("run", None)
    _save_manifest(root, manifest)
    return {"status": "ok", "root": root, "settings": data}


# ---------------------------------------------------------------------------
# Run groups (``"groups"`` in the manifest): processes started together
# ---------------------------------------------------------------------------

_GROUP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
_GROUP_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_GROUP_MEMBERS = 8


def groups_of(manifest: dict) -> List[RunGroup]:
    """The manifest's run groups, leniently: malformed entries are skipped
    (:func:`set_groups` is what refuses them)."""
    out: List[RunGroup] = []
    raw = manifest.get("groups")
    for g in raw if isinstance(raw, list) else []:
        if not isinstance(g, dict) or not isinstance(g.get("id"), str):
            continue
        members = []
        for m in g.get("members") if isinstance(g.get("members"), list) else []:
            if isinstance(m, dict) and isinstance(m.get("id"), str) and isinstance(m.get("target"), str):
                variables = m.get("variables") if isinstance(m.get("variables"), dict) else {}
                members.append(GroupMember(m["id"], m["target"].replace("\\", "/").strip("/"),
                                           {str(k): str(v) for k, v in variables.items()}))
        env = g.get("env") if isinstance(g.get("env"), dict) else {}
        out.append(RunGroup(g["id"], str(g.get("title") or ""), members,
                            {str(k): str(v) for k, v in env.items()}))
    return out


def find_group(manifest: dict, group_id: str) -> RunGroup:
    for group in groups_of(manifest):
        if group.id == group_id:
            return group
    raise TestProjectError(f"No run group {group_id!r} in this project.")


def _group_entry(runner: TestProjectRunner, group: RunGroup) -> dict:
    entry = asdict(group)
    entry["views"] = runner.group_views(group)
    entry["runnable"] = len(group.members) >= 2 and all(runner.can_run(m.target) for m in group.members)
    return entry


def validate_groups(root: str, runner: TestProjectRunner, groups) -> List[RunGroup]:
    """Check groups as the GUI sends them; returns them cleaned up."""
    if not isinstance(groups, list):
        raise TestProjectError("Run groups must be a list.")
    out: List[RunGroup] = []
    seen = set()
    for i, g in enumerate(groups):
        where = f"Group {i + 1}"
        if not isinstance(g, dict):
            raise TestProjectError(f"{where} must be an object.")
        unknown = set(g) - {"id", "title", "members", "env", "views", "runnable"}
        if unknown:
            raise TestProjectError(f"{where}: unknown keys {', '.join(sorted(unknown))}.")
        gid = str(g.get("id") or "").strip()
        if not _GROUP_ID_RE.match(gid):
            raise TestProjectError(f"{where}: the id {gid!r} must be letters, digits, '_' or '-' (at most 40).")
        if gid in seen:
            raise TestProjectError(f"Two groups are called {gid!r}.")
        seen.add(gid)
        where = f"Group {gid!r}"
        members_raw = g.get("members")
        if not isinstance(members_raw, list) or not 2 <= len(members_raw) <= MAX_GROUP_MEMBERS:
            raise TestProjectError(f"{where} needs 2 to {MAX_GROUP_MEMBERS} members.")
        members: List[GroupMember] = []
        member_ids = set()
        for m in members_raw:
            if not isinstance(m, dict):
                raise TestProjectError(f"{where}: every member must be an object.")
            mid = str(m.get("id") or "").strip()
            if not _GROUP_ID_RE.match(mid):
                raise TestProjectError(f"{where}: the member id {mid!r} must be letters, digits, '_' or '-'.")
            if mid in member_ids:
                raise TestProjectError(f"{where}: two members are called {mid!r}.")
            member_ids.add(mid)
            target = str(m.get("target") or "").replace("\\", "/").strip().strip("/")
            if not target:
                raise TestProjectError(f"{where}: member {mid!r} names no file.")
            _safe_join(root, target)
            if not runner.can_run(target):
                raise TestProjectError(f"{where}: {runner.display_name} cannot run {target}.")
            variables = m.get("variables") or {}
            if not isinstance(variables, dict):
                raise TestProjectError(f"{where}: member {mid!r}: variables must map names to values.")
            for name, value in variables.items():
                if not isinstance(name, str) or not _GROUP_VAR_RE.match(name):
                    raise TestProjectError(f"{where}: member {mid!r}: invalid variable name {name!r}.")
                if not isinstance(value, (str, int, float, bool)):
                    raise TestProjectError(f"{where}: member {mid!r}: variable {name} must be text.")
            members.append(GroupMember(mid, target, {k: str(v) for k, v in variables.items()}))
        env = g.get("env") or {}
        if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise TestProjectError(f"{where}: 'env' must map names to strings.")
        out.append(RunGroup(gid, str(g.get("title") or "").strip(), members,
                            {k.strip(): v for k, v in env.items() if k.strip()}))
    return out


def get_groups(root: str) -> dict:
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    runner = get_runner(manifest["runner"])
    return {"status": "ok", "root": root,
            "groups": [_group_entry(runner, g) for g in groups_of(manifest)]}


def set_groups(root: str, groups) -> dict:
    """Replace the project's run groups (an empty list removes them)."""
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    runner = get_runner(manifest["runner"])
    clean = validate_groups(root, runner, groups)
    if clean:
        manifest["groups"] = [asdict(g) for g in clean]
    else:
        manifest.pop("groups", None)
    _save_manifest(root, manifest)
    return {"status": "ok", "root": root, "groups": [_group_entry(runner, g) for g in clean]}


def inspect_group(root: str, group_id: str) -> dict:
    """The runner's views of a run group (every member's flow and where they meet)."""
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    runner = get_runner(manifest["runner"])
    group = find_group(manifest, group_id)
    views = runner.group_views(group)
    if not views:
        raise TestProjectError(f"Run group {group_id!r} has no views.")
    for m in group.members:
        if not os.path.isfile(_safe_join(root, m.target)):
            raise TestProjectError(f"Member {m.id} runs {m.target}, which does not exist.")
    result = runner.inspect_group(root, _layout(runner, manifest), group, run_settings_of(manifest))
    out = {"status": "ok", "group": group.id, "available": views}
    out.update(result)
    return out


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


def inspect_file(root: str, rel: str, content: Optional[str] = None) -> dict:
    """The runner's extra views of a file (e.g. a flow's diagram and Robot text).

    ``content`` is the editor's text; without it the file on disk is used.
    """
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    runner = get_runner(manifest["runner"])
    rel = str(rel).replace("\\", "/")
    full = _safe_join(root, rel)
    views = runner.file_views(rel)
    if not views:
        raise TestProjectError(f"{rel} has no views besides its text.")
    if content is None:
        if not os.path.isfile(full):
            raise TestProjectError(f"No such file in the test project: {rel}")
        content = _read_text(full)
    result = runner.inspect_file(root, _layout(runner, manifest), rel, content,
                                 run_settings_of(manifest))
    out = {"status": "ok", "path": rel, "available": views}
    out.update(result)
    return out


def edit_file_view(root: str, rel: str, view_id: str, content: str, edit: dict) -> dict:
    """Apply an edit made in one of a file's views to ``content`` (the editor's
    text); returns the new text for the editor. Only files the user owns
    (``yours``, ``starter``) are edited this way -- like in the editor."""
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    runner = get_runner(manifest["runner"])
    rel = str(rel).replace("\\", "/")
    _safe_join(root, rel)
    if not any(v["id"] == view_id for v in runner.file_views(rel)):
        raise TestProjectError(f"{rel} has no view {view_id!r}.")
    if _role_of(manifest, rel) not in _EDITABLE_ROLES:
        raise TestProjectError(f"{rel} is not edited here: it is written by an export.")
    if not isinstance(edit, dict):
        raise TestProjectError("The edit must be an object.")
    result = runner.edit_view(root, _layout(runner, manifest), rel, str(content), view_id, edit,
                              run_settings_of(manifest))
    out = {"status": "ok", "path": rel}
    out.update(result)
    return out


def define(root: str, rel: str, content: str, name: str) -> dict:
    """Where keyword (or import) ``name`` used in ``rel`` (the editor's ``content``)
    is defined, by the project's runner: ``found``, ``path`` (project-relative,
    when inside the project), ``abs``, ``line``, ``owner`` -- and for a file
    outside the project ``snippet``: ``{"first": n, "lines": [...]}`` around
    the line, read-only."""
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    runner = get_runner(manifest["runner"])
    layout = _layout(runner, manifest)
    rel = str(rel).replace("\\", "/")
    _safe_join(root, rel)
    res = dict(runner.define(root, layout, rel, content, str(name or ""), run_settings_of(manifest)) or {})
    source = res.get("source")
    if not res.get("found") or not source:
        return {"status": "ok", "found": False, "name": name, **({"error": res["error"]} if res.get("error") else {})}
    full = os.path.abspath(str(source))
    out = {"status": "ok", "found": True, "name": res.get("name") or name, "owner": res.get("owner") or "",
           "abs": full, "line": res.get("line"), "path": None}
    inside = os.path.normcase(full).startswith(os.path.normcase(root) + os.sep)
    if inside:
        out["path"] = os.path.relpath(full, root).replace(os.sep, "/")
    else:
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            lines = []
        at = max(1, int(res.get("line") or 1))
        first = max(1, at - 3)
        out["snippet"] = {"first": first, "lines": lines[first - 1:first - 1 + 40]}
    return out


def check_syntax(rel: str, content: str, root: Optional[str] = None) -> List[dict]:
    """Syntax problems of unsaved text: the parse error of a ``.json`` file
    (flow files included), else what the runner reports -- the project's
    runner when ``root`` is a test project, otherwise every registered one.

    Returns ``[{"line": n, "message": text}]``; empty when the text is fine
    or nobody can check it.
    """
    lower = str(rel).lower()
    if lower.endswith(".json"):
        try:
            json.loads(content)
        except ValueError as exc:
            return [{"line": getattr(exc, "lineno", 1),
                     "message": f"Invalid JSON: {getattr(exc, 'msg', exc)}"}]
        return []
    runners: List[TestProjectRunner] = []
    manifest = _load_manifest(_abs_root(root)) if root else None
    if manifest is not None:
        runners = [get_runner(manifest["runner"])]
    else:
        _load_plugins()
        runners = list(_RUNNERS.values())
    for runner in runners:
        problems = runner.check_syntax(rel, content)
        if problems:
            return problems
    return []


def write_project_file(root: str, rel: str, content: str, *,
                       expected_sha256: Optional[str] = None,
                       create: bool = False, force: bool = False) -> dict:
    """Save a user-owned file of a test project.

    Refuses generated files and the manifest (exports own them), paths
    outside the project, and -- unless ``force`` -- a file whose bytes on
    disk no longer match ``expected_sha256``
    (:class:`~MicroserviceBase.ports.test_project.TestProjectConflict`).
    With ``create=True`` the file must not exist and must be of a file type
    the runner lets the GUI create. Returns the new hash and any syntax
    problems.
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
        runner = get_runner(manifest["runner"])
        suffixes = [ft.suffix for ft in runner.file_types() if ft.creatable and ft.suffix]
        if not any(rel.lower().endswith(sfx.lower()) for sfx in suffixes):
            raise TestProjectError(
                f"New files of a {runner.display_name} project must end in "
                f"{', '.join(suffixes) or '(none: it creates no files here)'}.")
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
            "problems": check_syntax(rel, content, root)}


def _new_stem(name: str, suffix: str, noun: str) -> str:
    """The name the user typed, without the file type's suffix, if checked."""
    stem = str(name or "").strip()
    if suffix and stem.lower().endswith(suffix.lower()):
        stem = stem[: -len(suffix)]
    if not _NEW_SUITE_RE.match(stem):
        raise TestProjectError(
            f"Invalid {noun} name {name!r}: use letters, digits, '_' or '-' (no spaces).")
    return stem


def _new_folder(layout: Dict[str, str], ft: FileType) -> str:
    return (layout.get(ft.folder) or ft.folder or ".").strip("/") or "."


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

    ft = _file_type(runner, "suite")
    if ft is None or not ft.creatable:
        raise TestProjectError(f"{runner.display_name} projects cannot create suites here.")
    noun = ft.noun or "suite"
    stem = _new_stem(name, ft.suffix, noun)
    rel = f"{_new_folder(layout, ft)}/{stem}{ft.suffix}"

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
                           if (m or {}).get("role") == "generated"
                           and _kind(p, runner, layout) == "resource")
        consul_addr = entry.get("consul_addr") or DEFAULT_CONSUL
        if (entry.get("source") or {}).get("kind") == "proto":
            proto_rel_dir = f"{layout['proto']}/{service}"

    content = runner.suite_template(layout, rel, service, resources, consul_addr, proto_rel_dir)
    if not content:
        raise TestProjectError(f"{runner.display_name} projects cannot create a {noun} here.")
    return write_project_file(root, rel, content, create=True)


def create_flow(root: str, name: str, *, resources: Optional[List[str]] = None) -> dict:
    """Create a new flow file in the project's flows folder from the runner's template.

    ``resources``: project-relative resource files the flow imports, so their
    keywords can be its steps.
    """
    root = _abs_root(root)
    manifest = _load_manifest(root)
    if manifest is None:
        raise TestProjectError(f"{root} is not a test project.")
    runner = get_runner(manifest["runner"])
    layout = _layout(runner, manifest)
    ft = _file_type(runner, "flow")
    if ft is None or not ft.creatable:
        raise TestProjectError(f"{runner.display_name} projects have no flow files.")
    stem = _new_stem(name, ft.suffix, ft.noun or "flow")
    rel = f"{_new_folder(layout, ft)}/{stem}{ft.suffix}"
    picked = []
    for path in resources or []:
        path = str(path).replace("\\", "/").strip("/")
        _safe_join(root, path)
        if not os.path.isfile(os.path.join(root, *path.split("/"))):
            raise TestProjectError(f"{path} is not a file of this project.")
        picked.append(path)
    title = stem.replace("_", " ").replace("-", " ").strip().title()
    content = runner.flow_template(layout, rel, title, picked)
    if not content:
        raise TestProjectError(f"{runner.display_name} projects have no flow files.")
    return write_project_file(root, rel, content, create=True)
