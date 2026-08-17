#!/usr/bin/env python3
"""Verify rendered PlantUML output by DECODING it, not by counting it.

PlantUML renders a *failed* diagram as a perfectly well-formed SVG whose
content reads "Syntax Error" or "cannot include". Counting ``<svg>`` tags
or ``data:image/svg`` occurrences therefore reports success on broken
diagrams -- which is exactly how a docs build goes green while shipping
error images.

This script walks the built site, decodes every embedded diagram, and
fails if any of them contain PlantUML's error markers.

Usage
-----
    python tools/verify_diagrams.py [site_dir]

Exit codes
----------
    0  all diagrams rendered cleanly
    1  at least one diagram contains an error marker
    2  site directory missing
    3  no diagrams found at all (extension probably inactive)
"""

from __future__ import annotations

import base64
import re
import sys
import urllib.parse
from pathlib import Path

ERROR_MARKERS = (
    "cannot include",
    "syntax error",
    "contains errors",
    "an error has occurred",
    "java.lang.",
    "exception in thread",
)

SVG_INLINE_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL | re.IGNORECASE)

# Match the data-URI as a quoted ATTRIBUTE VALUE, not by excluding
# characters. base64 payloads legitimately contain '+' and '/', so a
# class like [^"')]* truncates them mid-payload -- the decode then yields
# garbage that contains no error markers, and every diagram silently
# "passes". Anchoring on the quotes keeps the payload intact.
SVG_DATA_RE = re.compile(r'(?:src|href)="(data:image/svg\+xml[^"]*)"')

PNG_IMG_RE = re.compile(r'<img[^>]+src="[^"]+\.png"')

# Diagram source that reached the page as a CODE BLOCK instead of an
# image -- i.e. the renderer for that language is not configured. This is
# how four Mermaid diagrams shipped as literal text while the PlantUML
# check reported everything green: the checker only looked at pages that
# already had images on them.
UNRENDERED_RE = re.compile(
    r"<code[^>]*>\s*(?:"
    r"@startuml|"
    r"flowchart\s+(?:TB|TD|LR|RL|BT)\b|"
    r"sequenceDiagram\b|"
    r"stateDiagram(?:-v2)?\b|"
    r"classDiagram\b|"
    r"erDiagram\b|"
    r"gantt\b|"
    r"graph\s+(?:TB|TD|LR|RL|BT)\b"
    r")",
    re.IGNORECASE,
)

# A genuine PlantUML diagram is built from many drawing primitives. An
# error image is essentially a text box, so shape count separates them
# even when the wording of the error is one we do not know about.
SHAPE_RE = re.compile(r"<(rect|path|polygon|ellipse|line|circle)\b", re.IGNORECASE)
MIN_SHAPES = 3


def decode_blobs(html: str):
    """Yield (kind, decoded_svg) for every diagram embedded in the page."""
    for m in SVG_INLINE_RE.finditer(html):
        yield "inline-svg", m.group(0)

    seen = set()
    for m in SVG_DATA_RE.finditer(html):
        raw = m.group(1)
        # glightbox wraps each <img> in an <a href> with the same payload;
        # count each diagram once.
        if raw in seen:
            continue
        seen.add(raw)

        meta, _, payload = raw.partition(",")
        if "base64" in meta:
            try:
                # padding: b64decode is strict about length % 4
                yield "data-uri", base64.b64decode(payload + "===").decode(
                    "utf-8", "replace"
                )
            except Exception as exc:  # pragma: no cover - diagnostic path
                yield "undecodable", f"base64 decode failed: {exc}"
        else:
            yield "data-uri", urllib.parse.unquote(payload)


def main(argv):
    site = Path(argv[1] if len(argv) > 1 else "site")
    if not site.is_dir():
        print(f"ERROR: site directory not found: {site}", file=sys.stderr)
        return 2

    total = 0
    broken = 0
    unrendered = 0
    png_pages = []

    for page in sorted(site.rglob("index.html")):
        html = page.read_text(encoding="utf-8", errors="replace")
        blobs = list(decode_blobs(html))
        rel = page.relative_to(site).as_posix()

        # Check EVERY page for diagram source that never became an image.
        # Skipping image-less pages (the old behaviour) is exactly why
        # four Mermaid blocks shipped as visible text unnoticed.
        for m in UNRENDERED_RE.finditer(html):
            unrendered += 1
            lang = m.group(0)
            lang = re.sub(r"<[^>]+>", "", lang).strip()
            print(f"FAIL {rel}: diagram source rendered as TEXT, not an image "
                  f"(starts with {lang!r})")

        if not blobs:
            continue

        if PNG_IMG_RE.search(html):
            png_pages.append(rel)

        page_bad = 0
        for idx, (kind, content) in enumerate(blobs):
            total += 1
            lowered = content.lower()
            hits = [mk for mk in ERROR_MARKERS if mk in lowered]
            shapes = len(SHAPE_RE.findall(content))

            problem = None
            if kind == "undecodable":
                problem = content
            elif hits:
                problem = f"error markers={hits}"
            elif shapes < MIN_SHAPES:
                # Catches error images whose wording we do not recognise,
                # and payloads that decoded into something that is not SVG.
                problem = f"only {shapes} drawing primitive(s) - not a real diagram"

            if problem:
                broken += 1
                page_bad += 1
                print(f"FAIL {rel} [{idx}] ({kind}) {problem}")
                snippet = " ".join(re.findall(r">([^<>]{3,80})<", content)[:6])
                if snippet:
                    print(f"     {snippet[:200]}")

        status = "FAIL" if page_bad else "ok"
        print(f"{status:4} {rel}: {len(blobs)} diagram blob(s)")

    print()
    if png_pages:
        print(
            "WARNING: PNG <img> tags found (expected inline SVG) on: "
            + ", ".join(png_pages[:5])
        )
    if total == 0 and unrendered == 0:
        print("ERROR: no diagrams found -- is plantuml_markdown active?")
        return 3

    print(f"RESULT: {total - broken} rendered ok, {broken} broken (of {total})")
    if unrendered:
        print(
            f"        {unrendered} diagram(s) left as TEXT -- no renderer is "
            f"configured for that language."
        )
    return 1 if (broken or unrendered) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
