"""Tiny loader for the `templates/` tree shipped alongside this package.

Each cpp_tmpl / python_tmpl helper that used to embed a multi-kilobyte
Python f-string now reads its template from a `.tmpl` file under
`templates/<lang>/<cluster>/<name>.tmpl`.

The template syntax is a custom ``string.Template`` subclass that uses
``@@{var}`` instead of ``$var``.  Why: the default ``$`` delimiter
conflicts with CMake (``${VAR}``) and bash (``$VAR``), and a single
``@`` conflicts with Doxygen (``@param``, ``@return``, ``@brief``).
Doubling to ``@@`` dodges every one of these — single ``@`` and
single ``$`` both stay as literal text.

Placeholder forms:

* ``@@{var}``  — braced, recommended (always unambiguous)
* ``@@var``    — unbraced (technically supported, but ``@@{var}`` is
  the convention because it can't be confused with following identifier
  chars in the source)
* ``@@@@``     — escape for a literal ``@@``

Unknown placeholders raise ``KeyError`` so missing variables fail fast
at generation time instead of shipping ``@@{placeholder}`` text to disk.

Loaded templates are cached in process for the lifetime of the
interpreter — they're tiny and they don't change at runtime.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template

_TEMPLATES_ROOT = Path(__file__).resolve().parent / "templates"


class _AtTemplate(Template):
    """``string.Template`` subclass using ``@@{var}`` instead of ``$var``."""
    delimiter = "@@"


@lru_cache(maxsize=None)
def _read(rel_path: str) -> str:
    """Read a template file once, cache for the process lifetime."""
    full = _TEMPLATES_ROOT / rel_path
    return full.read_text(encoding="utf-8")


def load_template(rel_path: str, /, **vars: object) -> str:
    """Render a template under `templates/` with `@@{var}` substitution.

    `rel_path` is forward-slash relative to `templates/`
    (e.g. ``"cpp/server/main.cpp.tmpl"``).  Unknown placeholders raise
    ``KeyError`` so missing variables fail fast at generation time
    instead of shipping ``@@{placeholder}`` text to disk.
    """
    return _AtTemplate(_read(rel_path)).substitute(vars)


def load_raw(rel_path: str) -> str:
    """Read a template file verbatim, skipping `@@{var}` substitution.

    Use for files that contain literal `@@` sequences which would
    otherwise be mistaken for placeholders — most commonly unified
    diffs / patches where `@@ -L,N +L,N @@` is the hunk-header syntax.
    """
    return _read(rel_path)
