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

# electron-builder sets ${INSTALL_DIR} for afterInstall hooks.
APP_RESOURCES="${INSTALL_DIR:-/opt/devatservgui}/resources"
BOOTSTRAP="$APP_RESOURCES/bootstrap.sh"

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
