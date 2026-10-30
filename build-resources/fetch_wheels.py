#!/usr/bin/env python3
"""Put the two wheels the installers bundle into build-resources/installers/.

* MicroserviceBase, at the version installer.nsh names (MSB_VER): built
  from $MSB_SRC when that points at a checkout of the base repo, else
  downloaded from the package index.
* microservice-gui-bridge, built from this repo's bridge/ (BRIDGE_VER must
  match bridge/pyproject.toml).

Run by build.sh, build.bat and the installer workflow. Exits non-zero
when a wheel is missing or a version disagrees, so an installer never
ships without the wheels it installs.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUI = HERE.parent
OUT = HERE / "installers"


def _define(nsh, name):
    m = re.search(r'!define\s+%s\s+"([^"]+)"' % name, nsh)
    if not m:
        sys.exit(f"installer.nsh: no !define {name}")
    return m.group(1)


def _wheel_version(path):
    # name-version-py3-none-any.whl
    return path.name.split("-")[1]


def main():
    nsh = (HERE / "installer.nsh").read_text(encoding="utf-8")
    msb_ver, bridge_ver = _define(nsh, "MSB_VER"), _define(nsh, "BRIDGE_VER")
    proj = (GUI / "bridge" / "pyproject.toml").read_text(encoding="utf-8")
    proj_ver = re.search(r'^version\s*=\s*"([^"]+)"', proj, re.M).group(1)
    if proj_ver != bridge_ver:
        sys.exit(f"installer.nsh BRIDGE_VER {bridge_ver} != bridge/pyproject.toml {proj_ver}")

    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.whl"):
        old.unlink()
    pip = [sys.executable, "-m", "pip"]
    # --no-build-isolation: no per-build venv, so it works offline when the
    # Python already has setuptools and wheel.
    build = pip + ["wheel", "--no-deps", "--no-build-isolation", "-w", str(OUT)]
    src = os.environ.get("MSB_SRC", "").strip()
    if src:
        subprocess.run(build + [src], check=True, env=dict(os.environ, SKIP_DOCBUILD="1"))
    else:
        subprocess.run(pip + ["download", "--no-deps", "--only-binary=:all:", "-d", str(OUT),
                              f"MicroserviceBase=={msb_ver}"], check=True)
    subprocess.run(build + [str(GUI / "bridge")], check=True)

    msb = sorted(OUT.glob("microservicebase-*.whl"))
    if len(msb) != 1 or _wheel_version(msb[0]) != msb_ver:
        sys.exit(f"expected microservicebase-{msb_ver}-*.whl, found {[p.name for p in msb]} "
                 f"(MSB_VER in installer.nsh and the base checkout must agree)")
    bridge = OUT / f"microservice_gui_bridge-{bridge_ver}-py3-none-any.whl"
    if not bridge.is_file():
        sys.exit(f"expected {bridge.name}")
    for p in sorted(OUT.glob("*.whl")):
        print(p.relative_to(GUI))


if __name__ == "__main__":
    main()
