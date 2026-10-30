#!/usr/bin/env bash
#
# Debian .deb postinst hook for DevAtServGUI.
#
# `apt install ./devatservgui_*.deb` runs this script as root after the
# files are unpacked.  We:
#   1. Detect Consul + Nomad on the host and report status.
#   2. If stdin is a TTY (the user invoked apt from a terminal), launch
#      the interactive bootstrap.sh so they can install / provide paths.
#   3. Otherwise (e.g. the deb was installed via Ansible / a CI pipeline),
#      print a clear note pointing at bootstrap.sh for the user to run
#      later.
#
# bootstrap.sh ships next to this file in /opt/<app>/resources/.

set -e

# electron-builder does not export an install-dir variable to this hook, and
# the app installs under its productName (/opt/DevAtServGUI), so use the
# first known location that actually holds our resources.
APP_RESOURCES=""
for _cand in "${INSTALL_DIR:-}/resources" /opt/DevAtServGUI/resources /opt/devatservgui/resources; do
    if [[ "$_cand" != "/resources" && -d "$_cand" ]]; then
        APP_RESOURCES="$_cand"
        break
    fi
done
APP_RESOURCES="${APP_RESOURCES:-/opt/DevAtServGUI/resources}"
BOOTSTRAP="$APP_RESOURCES/bootstrap.sh"
APP_DIR="$(dirname "$APP_RESOURCES")"

# What electron-builder's own after-install script does, which ours replaces:
# the `devatservgui` command, and the SUID sandbox helper Electron refuses
# to start without.
ln -sf "$APP_DIR/devatservgui" /usr/bin/devatservgui || true
if [[ -f "$APP_DIR/chrome-sandbox" ]]; then
    chown root:root "$APP_DIR/chrome-sandbox" || true
    chmod 4755 "$APP_DIR/chrome-sandbox" || true
fi

# MicroserviceBase and the bridge, in a venv of its own: Debian 12 and
# Ubuntu 23.04+ refuse pip installs into the system Python (PEP 668).
# Offline from the bundled wheelhouse when it has this Python's wheels,
# else from the package index (through apt's proxy if one is set).
PY_ENV="$APP_DIR/python-env"
PY_BIN="$PY_ENV/bin/python3"
MSB_WHEEL="$(ls "$APP_RESOURCES"/installers/microservicebase-*-py3-none-any.whl 2>/dev/null | head -n1 || true)"
BRIDGE_WHEEL="$(ls "$APP_RESOURCES"/installers/microservice_gui_bridge-*-py3-none-any.whl 2>/dev/null | head -n1 || true)"
echo
echo "DevAtServGUI: installing MicroserviceBase and the bridge into $PY_ENV"
if [[ -z "$MSB_WHEEL" || -z "$BRIDGE_WHEEL" ]]; then
    echo "  (the MicroserviceBase or bridge wheel is missing in $APP_RESOURCES/installers; skipped)"
elif ! command -v python3 >/dev/null 2>&1; then
    echo "  python3 NOT FOUND; install it, then: sudo dpkg-reconfigure devatservgui"
elif ! { [[ -x "$PY_BIN" ]] || python3 -m venv "$PY_ENV"; }; then
    rm -rf "$PY_ENV"
    echo "  could not create the venv; install python3-venv, then: sudo dpkg-reconfigure devatservgui"
else
    PIP=("$PY_BIN" -m pip install --quiet --no-cache-dir --disable-pip-version-check --upgrade)
    if [[ -d "$APP_RESOURCES/wheelhouse" ]] && \
       "${PIP[@]}" --no-index --find-links "$APP_RESOURCES/wheelhouse" "$MSB_WHEEL" "$BRIDGE_WHEEL"; then
        echo "  installed from the bundled wheels"
    else
        echo "  bundled wheels do not fit this Python; downloading the dependencies"
        if [[ -z "${https_proxy:-}${HTTPS_PROXY:-}" ]] && command -v apt-config >/dev/null 2>&1; then
            _proxy="$(apt-config shell P Acquire::https::Proxy 2>/dev/null; apt-config shell P Acquire::http::Proxy 2>/dev/null)"
            _proxy="$(eval "$_proxy"; echo "${P:-}")"
            [[ -n "$_proxy" && "$_proxy" != DIRECT ]] && export https_proxy="$_proxy" http_proxy="$_proxy"
        fi
        if "${PIP[@]}" "$MSB_WHEEL" "$BRIDGE_WHEEL"; then
            echo "  installed"
        else
            echo "  FAILED; retry with network access: sudo dpkg-reconfigure devatservgui"
        fi
    fi
    # Point the packaged default settings (root-owned, copied to new users)
    # at the venv; it ships the Windows interpreter path. Users' own
    # settings are not touched as root: the app picks the venv itself when
    # theirs name a system Python or a Windows path (preload.js).
    _settings="$APP_RESOURCES/settings.json"
    if [[ -x "$PY_BIN" && -f "$_settings" && ! -L "$_settings" ]]; then
        python3 - "$_settings" "$PY_BIN" <<'EOF' || true
import json, sys
path, py = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    s = json.load(f)
v = s.get("pythonPath", "")
if v in ("", "python", "python3", "/usr/bin/python", "/usr/bin/python3") or "\\" in v or v[1:3] in (":/", ":\\"):
    s["pythonPath"] = py
    with open(path, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    print("  settings: pythonPath set in", path)
EOF
    fi
fi

echo
echo "DevAtServGUI: post-install infrastructure check"
echo "-----------------------------------------------"

CONSUL_PATH="$(command -v consul 2>/dev/null || true)"
NOMAD_PATH="$(command -v nomad  2>/dev/null || true)"

if [[ -n "$CONSUL_PATH" ]]; then
    echo "  consul: detected at $CONSUL_PATH"
else
    echo "  consul: NOT FOUND"
fi
if [[ -n "$NOMAD_PATH" ]]; then
    echo "  nomad:  detected at $NOMAD_PATH"
else
    echo "  nomad:  NOT FOUND"
fi

# Both present — nothing to do.
if [[ -n "$CONSUL_PATH" && -n "$NOMAD_PATH" ]]; then
    echo
    echo "Both tools found.  No further action needed."
    exit 0
fi

if [[ -t 0 && -t 1 ]]; then
    echo
    echo "Launching interactive bootstrap to fix missing tool(s)..."
    if [[ -x "$BOOTSTRAP" ]]; then
        bash "$BOOTSTRAP" || true
    else
        echo "  (bootstrap.sh not found at $BOOTSTRAP — skipping interactive setup)"
    fi
else
    echo
    echo "To finish setup, run the bootstrap script interactively:"
    echo "    bash $BOOTSTRAP"
fi

exit 0
