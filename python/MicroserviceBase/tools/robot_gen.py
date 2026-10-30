#!/usr/bin/env python3
"""Generate Robot Framework resource files from a .proto folder.

For every ``service`` declared in any ``.proto`` under ``--proto-dir``,
emit a self-contained ``<snake_service>.resource`` file with one keyword
per RPC method.  See :mod:`MicroserviceBase.adapters.scaffold.robot_tmpl`
for the underlying generator.

Standalone — does NOT require the bridge to be running.  Calls the
generator in-process so it works in CI / from a plain shell.

Usage::

    python -m MicroserviceBase.tools.robot_gen \\
        --proto-dir D:/Project/.../MultiProto2/proto \\
        --out      ./tests/resources

    # Only generate one of the services
    python -m MicroserviceBase.tools.robot_gen \\
        --proto-dir ./proto --out ./tests \\
        --service ComSetupDeviceService

    # Print to stdout instead of writing files (handy in pipes)
    python -m MicroserviceBase.tools.robot_gen --proto-dir ./proto --stdout
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List

from MicroserviceBase.adapters.scaffold.robot_tmpl import (
    RobotGenError,
    generate_robot_resources,
)


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m MicroserviceBase.tools.robot_gen",
        description=__doc__.splitlines()[0],
    )
    p.add_argument(
        "--proto-dir", required=True,
        help="Folder containing one or more .proto files (non-recursive).",
    )
    p.add_argument(
        "--out",
        help="Folder to write .resource files into (created if missing). "
             "Required unless --stdout is given.",
    )
    p.add_argument(
        "--service", action="append", default=[],
        help="Only emit a resource for this service name "
             "(repeatable; default: all services).",
    )
    p.add_argument(
        "--stdout", action="store_true",
        help="Print every generated resource to stdout, separated by a "
             "comment header.  Useful for piping into a diff or a single file.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Overwrite existing .resource files in --out (default: refuse).",
    )
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if not args.stdout and not args.out:
        print("ERROR: pass --out <dir> or --stdout", file=sys.stderr)
        return 2

    try:
        files = generate_robot_resources(
            args.proto_dir,
            service_filter=args.service or None,
        )
    except RobotGenError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.stdout:
        for path, content in files.items():
            print(f"# ============== {path} ==============")
            print(content, end="")
        return 0

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []
    skipped: List[str] = []
    for relpath, content in files.items():
        target = os.path.join(out_dir, relpath)
        if os.path.exists(target) and not args.force:
            skipped.append(target)
            continue
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        written.append(target)

    for w in written:
        print(f"wrote   {w}")
    for s in skipped:
        print(f"skipped {s}  (use --force to overwrite)")

    if skipped and not written:
        print("Nothing written.  Use --force to overwrite the skipped files.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
