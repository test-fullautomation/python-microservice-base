#!/bin/bash

set -e

COL_GREEN='\033[0;32m'
COL_ORANGE='\033[0;33m'
COL_BLUE='\033[0;34m'
COL_RED='\033[1;31m'
COL_RESET='\033[0m' # No Color

MSG_INFO="${COL_GREEN}[INFO]${COL_RESET}"
MSG_DONE="${COL_ORANGE}[DONE]${COL_RESET}"
MSG_ERR="${COL_RED}[ERR]${COL_RESET} "


CURRENT_USER=${SUDO_USER}
if [ -z ${CURRENT_USER} ]; then
   CURRENT_USER=$(whoami)
fi
# When executing as root user $HOME can be /root
# Otherwises, /home/<user> should be used
if [ ${CURRENT_USER} != 'root' ]; then
   HOME=/home/${CURRENT_USER}
fi

#in osd4 group name is the user name.
#in osd5 group name is "domain users". Therefore
#look if a group wi th the user name exists, if not
#then we assume that we are on OSD5
sGROUP=$(id -G)
if ! getent group "${sGROUP}" | grep "${sGROUP}" ; then
   sGROUP='domain users'
   echo -e "Assuming OSD7 and using group 'domain users' as user group for private files"
else
   echo -e "Assuming OSD4 and using group ${sGROUP} as user group for private files"
fi



# Configure Unitiy Launchers folder
APPS_PATH=${HOME}/.local/share/applications
if [ -e "${APPS_PATH}" ]; then
   # Check whether it is file or directory
   # remove it in case it is fine then create appropriate directory 
   if [ -f "${APPS_PATH}" ]; then
      rm "${APPS_PATH}"
      mkdir "${APPS_PATH}"
   fi
else
   # Create applications launcher folder if not existing
   mkdir "${APPS_PATH}"
fi


echo -e "${MSG_DONE} Device Automation Services App has been successfully created/updated."
cp /opt/devatserv/share/applications/devatserv.desktop ${APPS_PATH}/devatserv.desktop
chown -R "${CURRENT_USER}:${sGROUP}" ${APPS_PATH}/devatserv.desktop
chmod +x ${APPS_PATH}/devatserv.desktop