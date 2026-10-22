#!/usr/bin/env bash
#
# Debian .deb postrm hook for DevAtServGUI.
#
# Removes what postinst.sh made outside the package's file list: the
# `devatservgui` command and the MicroserviceBase venv. Upgrades keep both.
#
# Also undoes the BITS Platform services add-on (install-bits-platform.sh
# kept a copy of itself next to them). `apt remove` takes away the
# environment and udev rules and leaves the services; `apt purge` deletes
# them too.
case "${1:-remove}" in
  remove|purge)
    [ "$(readlink /usr/bin/devatservgui 2>/dev/null)" = /opt/DevAtServGUI/devatservgui ] && rm -f /usr/bin/devatservgui
    rm -rf /opt/DevAtServGUI/python-env
    rmdir /opt/DevAtServGUI 2>/dev/null
    ;;
esac
BITS="/opt/BITS_Platform_Service/.devatservgui-bits.sh"
case "${1:-remove}" in
  remove) [ -x "$BITS" ] && "$BITS" --remove ;;
  purge)  [ -x "$BITS" ] && "$BITS" --remove --purge ;;
esac
exit 0
