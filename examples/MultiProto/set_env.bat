@echo off
:: Central environment for MSVC builds.
::
:: THESE VALUES ALWAYS OVERWRITE whatever is in the parent shell.
:: Edit them directly to match your machine — that way a previous bad
:: 'set' in the shell can't stick around and break subsequent runs.
::
:: For MinGW builds use set_env_mingw.bat instead (called by
:: build_deploy_mingw.bat).

set "VCPKG_ROOT=C:\vcpkg"

:: CMake / Ninja — absolute paths; prepended to PATH if the exe exists.
set "CMAKE_DIR=C:\Program Files\CMake\bin"
set "NINJA_DIR="

if exist "%CMAKE_DIR%\cmake.exe" set "PATH=%CMAKE_DIR%;%PATH%"
if defined NINJA_DIR if exist "%NINJA_DIR%\ninja.exe" set "PATH=%NINJA_DIR%;%PATH%"

:: MSVC compiler — call vcvars64.bat to set cl.exe, link.exe, Windows SDK.
:: Skip if already initialised (VSCMD_ARG_TGT_ARCH is set by vcvars itself).
set "VS_DEV_CMD=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not defined VSCMD_ARG_TGT_ARCH (
    if exist "%VS_DEV_CMD%" (
        call "%VS_DEV_CMD%" >nul
    )
)
set "QT_DIR=C:\Qt\6.7.1\msvc2019_64"

set "MSBASE_ENV_LOADED=msvc"

echo ==== set_env (MSVC) applied ====
echo   VCPKG_ROOT = %VCPKG_ROOT%
echo   CMAKE_DIR  = %CMAKE_DIR%
echo   NINJA_DIR  = %NINJA_DIR%
echo   VS_DEV_CMD = %VS_DEV_CMD%
echo   QT_DIR     = %QT_DIR%
echo ==================================
