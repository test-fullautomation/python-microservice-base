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
Storage for Manager GUI bench compositions.

A composition says which components one bench shows for one role (the
ribbon tab it opens on): ``<dir>/<bench>/<role>.json``. It references
components by Consul service name and never copies their manifests; the
GUI lints it (``web/js/endo/contract/lint.js``), this store only checks
what it needs to keep the files sane.

The directory is per user, next to the bridge's agent logs, until the
configuration service's testbench scope can hold compositions:

* Windows: ``%APPDATA%\\devatservgui\\compositions``
* macOS:   ``~/Library/Application Support/devatservgui/compositions``
* Linux:   ``$XDG_CONFIG_HOME/devatservgui/compositions``

``MB_COMPOSITIONS_DIR`` overrides it (tests, shared bench PCs).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

COMPOSITIONS_DIR_ENV = "MB_COMPOSITIONS_DIR"

#: Ribbon tabs a composition can open on.
ROLES = ("user", "dev", "admin")

#: Largest composition accepted; a composition only lists references.
MAX_BYTES = 256 * 1024

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class CompositionError(ValueError):
   """A bench/role name or a composition body the store refuses."""


def default_dir() -> Path:
   """
Per-user directory holding the compositions.

**Returns:**

* ``path``

  / *Type*: Path /

  ``MB_COMPOSITIONS_DIR`` when set, else the platform default.
   """
   override = os.environ.get(COMPOSITIONS_DIR_ENV, "").strip()
   if override:
      return Path(override)
   if sys.platform.startswith("win"):
      base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
   elif sys.platform == "darwin":
      base = Path.home() / "Library" / "Application Support"
   else:
      base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
   return base / "devatservgui" / "compositions"


def check_names(bench: str, role: str) -> None:
   """
Refuse bench and role names that are not plain file names.

**Arguments:**

* ``bench``

  / *Condition*: required / *Type*: str /

  Bench name, e.g. ``bench07``: letters, digits, ``.``, ``_``, ``-``.

* ``role``

  / *Condition*: required / *Type*: str /

  One of ``user``, ``dev``, ``admin``.

**Raises:**

* ``CompositionError`` when either name is refused.
   """
   if not isinstance(bench, str) or not _NAME_RE.match(bench) or bench in (".", ".."):
      raise CompositionError(
         f"Invalid bench name {bench!r}: use letters, digits, '.', '_' or '-' (max 64).")
   if role not in ROLES:
      raise CompositionError(f"Invalid role {role!r}: use one of {', '.join(ROLES)}.")


def check_body(body: Any) -> None:
   """
Refuse a body that cannot be a composition. Rules (R3, R9, ...) are the
GUI linter's job; this keeps malformed files out of the store.

**Arguments:**

* ``body``

  / *Condition*: required / *Type*: Any /

  The parsed JSON the GUI sent.

**Raises:**

* ``CompositionError`` when the body is not an object with a
  ``components`` list of objects, or is too large.
   """
   if not isinstance(body, dict):
      raise CompositionError("A composition is a JSON object.")
   comps = body.get("components")
   if not isinstance(comps, list) or not all(isinstance(c, dict) for c in comps):
      raise CompositionError("'components' must be a list of objects.")
   if len(json.dumps(body)) > MAX_BYTES:
      raise CompositionError(f"Composition is larger than {MAX_BYTES // 1024} KB.")


class CompositionStore:
   """
Reads and writes ``<root>/<bench>/<role>.json``.

**Arguments:**

* ``root``

  / *Condition*: optional / *Type*: Path | str /

  Store directory; ``default_dir()`` when omitted.
   """

   def __init__(self, root: Optional[os.PathLike] = None):
      self.root = Path(root) if root else default_dir()

   def _path(self, bench: str, role: str) -> Path:
      check_names(bench, role)
      return self.root / bench / f"{role}.json"

   def list(self) -> List[Dict[str, Any]]:
      """
Every stored composition.

**Returns:**

* ``entries``

  / *Type*: List[dict] /

  ``{"bench", "role", "composition", "modified"}`` sorted by bench and
  role; ``composition`` is the file's ``composition`` field (may be "").
      """
      out: List[Dict[str, Any]] = []
      if not self.root.is_dir():
         return out
      for bench_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
         if not _NAME_RE.match(bench_dir.name):
            continue
         for role in ROLES:
            f = bench_dir / f"{role}.json"
            if not f.is_file():
               continue
            try:
               name = json.loads(f.read_text(encoding="utf-8")).get("composition", "")
            except (OSError, ValueError, AttributeError):
               name = ""
            out.append({"bench": bench_dir.name, "role": role,
                        "composition": name if isinstance(name, str) else "",
                        "modified": f.stat().st_mtime})
      return out

   def get(self, bench: str, role: str) -> Optional[Dict[str, Any]]:
      """
One composition, or ``None`` when it is not stored.

**Raises:**

* ``CompositionError`` for invalid names or a file that is not valid JSON.
      """
      f = self._path(bench, role)
      if not f.is_file():
         return None
      try:
         return json.loads(f.read_text(encoding="utf-8"))
      except ValueError as exc:
         raise CompositionError(f"{f} is not valid JSON: {exc}") from exc

   def put(self, bench: str, role: str, body: Dict[str, Any]) -> Path:
      """
Store a composition, replacing any previous one atomically.

**Returns:**

* ``path``

  / *Type*: Path /

  The file written.
      """
      f = self._path(bench, role)
      check_body(body)
      f.parent.mkdir(parents=True, exist_ok=True)
      tmp = f.with_suffix(".json.tmp")
      tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
      os.replace(tmp, f)
      return f

   def delete(self, bench: str, role: str) -> bool:
      """
Remove a composition. Returns ``False`` when it was not stored.
      """
      f = self._path(bench, role)
      if not f.is_file():
         return False
      f.unlink()
      try:
         f.parent.rmdir()   # only succeeds when the bench has no other role left
      except OSError:
         pass
      return True


def register_routes(app, store_factory=CompositionStore) -> None:
   """
Add the composition endpoints to the bridge app.

* ``GET    /api/ui/compositions``                 list
* ``GET    /api/ui/compositions/{bench}/{role}``  one (``code: not_found``)
* ``PUT    /api/ui/compositions/{bench}/{role}``  store (JSON body)
* ``DELETE /api/ui/compositions/{bench}/{role}``  remove

Responses follow the bridge convention ``{"status": "ok" | "error", ...}``.
The store is created per request so ``MB_COMPOSITIONS_DIR`` changes apply.
   """
   from fastapi import Body

   def _err(exc, code="invalid"):
      return {"status": "error", "code": code, "error": str(exc)}

   @app.get("/api/ui/compositions")
   def compositions_list():
      store = store_factory()
      return {"status": "ok", "dir": str(store.root), "compositions": store.list()}

   @app.get("/api/ui/compositions/{bench}/{role}")
   def compositions_get(bench: str, role: str):
      try:
         body = store_factory().get(bench, role)
      except CompositionError as exc:
         return _err(exc)
      if body is None:
         return _err(f"No composition stored for {bench}/{role}.", "not_found")
      return {"status": "ok", "bench": bench, "role": role, "composition": body}

   @app.put("/api/ui/compositions/{bench}/{role}")
   def compositions_put(bench: str, role: str, body: Any = Body(...)):
      try:
         path = store_factory().put(bench, role, body)
      except CompositionError as exc:
         return _err(exc)
      return {"status": "ok", "bench": bench, "role": role, "path": str(path)}

   @app.delete("/api/ui/compositions/{bench}/{role}")
   def compositions_delete(bench: str, role: str):
      try:
         removed = store_factory().delete(bench, role)
      except CompositionError as exc:
         return _err(exc)
      if not removed:
         return _err(f"No composition stored for {bench}/{role}.", "not_found")
      return {"status": "ok", "bench": bench, "role": role}
