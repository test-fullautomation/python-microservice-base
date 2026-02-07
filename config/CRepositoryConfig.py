# **************************************************************************************************************
#
#  Copyright 2020-2025 Robert Bosch GmbH
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
#
# **************************************************************************************************************
#
# CRepositoryConfig.py
#
# XC-CT/ECA3-Queckenstedt
#
# Purpose:
# - Compute and store all repository specific information, like the repository name,
#   paths to repository subfolder, paths to interpreter and so on ...
#
# - All paths to subfolder depends on the repository root path that has to be provided
#   to constructor of CRepositoryConfig
#
# --------------------------------------------------------------------------------------------------------------
#
# 02.02.2023
#
# --------------------------------------------------------------------------------------------------------------

import os, sys, platform, json
import importlib.util
import colorama as col

# Load version directly from file to avoid triggering MicroserviceBase/__init__.py
# which imports runtime dependencies (pika, etc.) not available during build
_version_path = os.path.join(os.path.dirname(__file__), "..", "MicroserviceBase", "version.py")
_spec = importlib.util.spec_from_file_location("MicroserviceBase.version", _version_path)
_version_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_version_mod)
VERSION = _version_mod.VERSION
VERSION_DATE = _version_mod.VERSION_DATE

col.init(autoreset=True)
COLBR = col.Style.BRIGHT + col.Fore.RED
COLBG = col.Style.BRIGHT + col.Fore.GREEN

# --------------------------------------------------------------------------------------------------------------

def printerror(sMsg):
    sys.stderr.write(COLBR + f"Error: {sMsg}!\n")

def printexception(sMsg):
    sys.stderr.write(COLBR + f"Exception: {sMsg}!\n")

def normalize_path(sPath):
    """Normalize path separators to forward slashes."""
    if sPath is None:
        return None
    return sPath.replace("\\", "/")

# --------------------------------------------------------------------------------------------------------------

class CRepositoryConfig():

    def __init__(self, sCalledBy=None):

        sCalledBy = normalize_path(sCalledBy)
        self.__sReferencePath = os.path.dirname(sCalledBy)

        self.__dictRepositoryConfig = None # initialized below by json.load()

        # load static configuration values (name of json file is fix)
        sRepositoryConfigurationFile = normalize_path(f"{self.__sReferencePath}/config/repository_config.json")
        hRepositoryConfigurationFile = open(sRepositoryConfigurationFile, encoding="utf-8")
        self.__dictRepositoryConfig = json.load(hRepositoryConfigurationFile)
        hRepositoryConfigurationFile.close()

        # add further infos
        # (to have the possibility to print out all values with help of 'PrintConfig()')
        self.__dictRepositoryConfig['CALLEDBY']                    = sCalledBy
        self.__dictRepositoryConfig['CWD']                         = os.getcwd()
        self.__dictRepositoryConfig['REFERENCEPATH']               = self.__sReferencePath
        self.__dictRepositoryConfig['REPOSITORYCONFIGURATIONFILE'] = sRepositoryConfigurationFile

        # add version and date of the package this repository configuration belongs to
        self.__dictRepositoryConfig['PACKAGEVERSION'] = VERSION
        self.__dictRepositoryConfig['PACKAGEDATE']    = VERSION_DATE

        # make absolute path to package documentation
        sPackageDoc = self.__dictRepositoryConfig.get('PACKAGEDOC', './packagedoc')
        if sPackageDoc.startswith('./'):
            sPackageDoc = normalize_path(os.path.join(self.__sReferencePath, sPackageDoc[2:]))
        self.__dictRepositoryConfig['PACKAGEDOC'] = sPackageDoc

        # compute dynamic configuration values
        bSuccess, sResult = self.__InitConfig()
        if bSuccess != True:
            raise Exception(sResult)
        print(COLBG + sResult)
        print()


    def __del__(self):
        del self.__dictRepositoryConfig


    def __InitConfig(self):

        sOSName         = os.name
        sPlatformSystem = platform.system()
        sPythonPath     = normalize_path(os.path.dirname(sys.executable))
        sPython         = normalize_path(sys.executable)
        sPythonVersion  = sys.version

        sInstalledPackageFolder = None

        if sPlatformSystem == "Windows":
            sInstalledPackageFolder = f"{sPythonPath}/Lib/site-packages/" + self.__dictRepositoryConfig['PACKAGENAME']
        elif sPlatformSystem == "Linux":
            sInstalledPackageFolder = f"{sPythonPath}/../lib/python3.10/site-packages/" + self.__dictRepositoryConfig['PACKAGENAME']
        else:
            bSuccess = False
            sResult  = f"Operating system {sPlatformSystem} ({sOSName}) not supported"
            return bSuccess, sResult

        self.__dictRepositoryConfig['OSNAME']                 = sOSName
        self.__dictRepositoryConfig['PLATFORMSYSTEM']         = sPlatformSystem
        self.__dictRepositoryConfig['PYTHON']                 = sPython
        self.__dictRepositoryConfig['PYTHONVERSION']          = sPythonVersion
        self.__dictRepositoryConfig['INSTALLEDPACKAGEFOLDER'] = sInstalledPackageFolder

        # ---- paths relative to repository root folder (where the scripts are located that use this module)

        # ====== 1. documentation

        # - README
        self.__dictRepositoryConfig['README_RST'] = normalize_path(f"{self.__sReferencePath}/README.rst")
        self.__dictRepositoryConfig['README_MD']  = normalize_path(f"{self.__sReferencePath}/README.md")

        # The following key doesn't matter in case of the documentation builder itself is using this CRepositoryConfig.
        # But if the documentation builder is called by other apps like setup.py, they need to know where to find.
        self.__dictRepositoryConfig['DOCUMENTATIONBUILDER'] = normalize_path(f"{self.__sReferencePath}/genpackagedoc.py")

        # - folder containing the package source files (will also contain the PDF documentation)
        self.__dictRepositoryConfig['PACKAGESOURCEFOLDER'] = normalize_path(f"{self.__sReferencePath}/{self.__dictRepositoryConfig['PACKAGENAME']}")

        # ====== 2. setuptools

        self.__dictRepositoryConfig['SETUPBUILDFOLDER']           = normalize_path(f"{self.__sReferencePath}/build")
        self.__dictRepositoryConfig['SETUPBUILDLIBFOLDER']        = normalize_path(f"{self.__sReferencePath}/build/lib")
        self.__dictRepositoryConfig['SETUPBUILDLIBPACKAGEFOLDER'] = normalize_path(f"{self.__sReferencePath}/build/lib/{self.__dictRepositoryConfig['PACKAGENAME']}")
        self.__dictRepositoryConfig['SETUPDISTFOLDER']            = normalize_path(f"{self.__sReferencePath}/dist")
        EGGINFOFOLDER = self.__dictRepositoryConfig['PACKAGENAME'].replace('-', '_')
        self.__dictRepositoryConfig['EGGINFOFOLDER']              = normalize_path(f"{self.__sReferencePath}/{EGGINFOFOLDER}.egg-info")

        print()
        print(f"Running under {sPlatformSystem} ({sOSName})")
        self.PrintConfig()

        bSuccess = True
        sResult  = "Repository setup done"
        return bSuccess, sResult

    # eof def __InitConfig(self):


    def PrintConfig(self):
        # -- printing configuration to console
        nJust = 30
        print()
        for sKey in self.__dictRepositoryConfig:
            print(sKey.rjust(nJust, ' ') + " : " + str(self.__dictRepositoryConfig[sKey]))
        print()
    # eof def PrintConfig(self):


    def Get(self, sName=None):
        if ( (sName is None) or (sName not in self.__dictRepositoryConfig) ):
            print()
            printerror(f"Error: Configuration parameter '{sName}' not existing!")
            # from here it's standard output:
            print("Use instead one of:")
            self.PrintConfig()
            return None # returning 'None' in case of key is not existing !!!
        else:
            return self.__dictRepositoryConfig[sName]
    # eof def Get(self, sName=None):


    def GetConfig(self):
       return self.__dictRepositoryConfig
    # eof def GetConfig(self):

# eof class CRepositoryConfig():

# --------------------------------------------------------------------------------------------------------------
