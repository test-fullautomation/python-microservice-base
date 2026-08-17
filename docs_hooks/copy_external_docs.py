"""ProperDocs/MkDocs build hook: pull in docs that live outside docs_dir.

Why a hook instead of moving the files
--------------------------------------
The Manager GUI docs and the examples docs cannot simply be relocated into
``docs/``:

* ``MicroserviceManagerGUI/docs/html/*.html`` are **shipped runtime assets** --
  the in-app help (``web/docs/help.html``) links to them and
  ``package.json`` bundles ``docs/html/**/*`` into the Electron installer.
* ``examples/docs/`` is bundled into the installer too (``extraResources``)
  and is meant to sit next to the example code it describes.

Their Markdown is nevertheless the canonical source for those guides, so we
copy it into ``docs/`` at build time and rewrite the links that only made
sense from the original location. The copies are gitignored; the originals
stay put and keep working for the GUI and the installer.

Copied trees
------------
    MicroserviceBase/MicroserviceManagerGUI/docs/md/*.md -> docs/gui/
    MicroserviceBase/MicroserviceManagerGUI/docs/img/*   -> docs/gui/img/
    examples/docs/md/*.md                                -> docs/examples/
"""

from __future__ import annotations

import logging
import posixpath
import re
import shutil
from pathlib import Path

log = logging.getLogger("mkdocs.hooks.copy_external_docs")

REPO = Path(__file__).resolve().parent.parent

GH_BLOB = "https://github.com/test-fullautomation/python-microservice-base/blob/develop"

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")

# Relative prefixes the rewriters legitimately produce -- these point at
# sibling pages inside the generated site and must NOT be absolutized.
_INTERNAL_PREFIXES = ("../examples/", "../gui/")


def _absolutize_escaping_links(text: str, src_rel_dir: str) -> str:
    """Turn any remaining ``../``-escaping link into a GitHub blob URL.

    Links are resolved against ``src_rel_dir`` -- the file's ORIGINAL
    repo-relative directory -- because that is what the author wrote them
    against. Anything that still climbs out of ``docs/`` after the
    targeted rewrites simply has no in-site equivalent (repo READMEs,
    example source trees), so pointing at GitHub is the honest answer.
    """

    def repl(m):
        label, target, title = m.group(1), m.group(2), m.group(3) or ""
        if target.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        if not target.startswith("../"):
            return m.group(0)
        if target.startswith(_INTERNAL_PREFIXES):
            return m.group(0)

        anchor = ""
        if "#" in target:
            target, anchor = target.split("#", 1)
            anchor = "#" + anchor

        resolved = posixpath.normpath(posixpath.join(src_rel_dir, target))
        resolved = resolved.lstrip("./")
        while resolved.startswith("../"):
            resolved = resolved[3:]
        return f"[{label}]({GH_BLOB}/{resolved}{anchor}{title})"

    return LINK_RE.sub(repl, text)

GUI_MD = REPO / "MicroserviceBase" / "MicroserviceManagerGUI" / "docs" / "md"
GUI_IMG = REPO / "MicroserviceBase" / "MicroserviceManagerGUI" / "docs" / "img"
EX_MD = REPO / "examples" / "docs" / "md"

# Destination dirs (relative to docs_dir). Both are gitignored.
GUI_DEST = "gui"
EX_DEST = "examples"

# Marker dropped into every generated dir so it is obvious in a file
# listing that the content is a build artefact and must not be edited.
README_STAMP = """\
<!--
  GENERATED DIRECTORY - DO NOT EDIT, DO NOT COMMIT.

  Populated at docs-build time by docs_hooks/copy_external_docs.py from:
      {source}

  Edit the source files there instead; this directory is gitignored and
  is recreated on every `properdocs build` / `properdocs serve`.
-->
"""


def _rewrite_gui(text: str) -> str:
    """Fix links in Manager GUI docs copied from docs/md/ to docs/gui/."""
    # ../../../../examples/docs/md/X.md  ->  ../examples/X.md
    text = re.sub(
        r"\((?:\.\./)+examples/docs/md/([A-Za-z0-9_\-]+\.md)\)",
        r"(../examples/\1)",
        text,
    )
    # ../img/X.png -> img/X.png   (images are copied into docs/gui/img/)
    text = re.sub(r"\(\.\./img/", "(img/", text)
    # ../html/X.html -> X.md   (the shipped HTML twin is not part of this site)
    text = re.sub(r"\(\.\./html/([A-Za-z0-9_\-]+)\.html\)", r"(\1.md)", text)
    return text


def _rewrite_examples(text: str) -> str:
    """Fix links in examples docs copied from examples/docs/md/ to docs/examples/."""
    # ../../../MicroserviceBase/MicroserviceManagerGUI/docs/md/X.md -> ../gui/X.md
    text = re.sub(
        r"\((?:\.\./)+MicroserviceBase/MicroserviceManagerGUI/docs/md/([A-Za-z0-9_\-]+\.md)\)",
        r"(../gui/\1)",
        text,
    )
    text = re.sub(r"\(\.\./img/", "(img/", text)
    text = re.sub(r"\(\.\./html/([A-Za-z0-9_\-]+)\.html\)", r"(\1.md)", text)
    return text


def _sync_markdown(src_dir: Path, dest_dir: Path, rewriter) -> int:
    if not src_dir.is_dir():
        log.warning("copy_external_docs: source missing: %s", src_dir)
        return 0
    src_rel_dir = src_dir.relative_to(REPO).as_posix()
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / ".generated").write_text(
        README_STAMP.format(source=src_rel_dir),
        encoding="utf-8",
    )
    count = 0
    for md in sorted(src_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        text = rewriter(text)
        # Catch anything the targeted rules did not cover.
        text = _absolutize_escaping_links(text, src_rel_dir)
        (dest_dir / md.name).write_text(text, encoding="utf-8", newline="\n")
        count += 1
    return count


def _sync_images(src_dir: Path, dest_dir: Path) -> int:
    if not src_dir.is_dir():
        return 0
    images = [p for p in src_dir.iterdir() if p.is_file()]
    if not images:
        return 0
    dest_dir.mkdir(parents=True, exist_ok=True)
    for img in images:
        shutil.copy2(img, dest_dir / img.name)
    return len(images)


def on_pre_build(config, **kwargs):
    """Populate docs/gui/ and docs/examples/ before MkDocs collects files."""
    docs_dir = Path(config["docs_dir"])

    gui_dest = docs_dir / GUI_DEST
    ex_dest = docs_dir / EX_DEST

    # Wipe first so a deleted source file does not linger as a stale page.
    for d in (gui_dest, ex_dest):
        if d.exists():
            shutil.rmtree(d)

    n_gui = _sync_markdown(GUI_MD, gui_dest, _rewrite_gui)
    n_img = _sync_images(GUI_IMG, gui_dest / "img")
    n_ex = _sync_markdown(EX_MD, ex_dest, _rewrite_examples)

    log.info(
        "copy_external_docs: %d GUI page(s) + %d image(s), %d example page(s)",
        n_gui,
        n_img,
        n_ex,
    )
