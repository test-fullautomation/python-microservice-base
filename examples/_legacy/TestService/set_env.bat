@echo off
:: Central environment for MSVC builds.
::
:: THESE VALUES ALWAYS OVERWRITE whatever is in the parent shell.
:: Edit them directly to match your machine — that way a previous bad
:: 'set' in the shell (e.g. leftover QT_DIR from build_deploy_msys2.bat)
:: can't stick around and poison the MSVC build with MinGW headers.
::
:: For MinGW builds use set_env_mingw.bat instead (called by
:: build_deploy_mingw.bat).
:: For MSYS2 builds use set_env_msys2.bat instead (called by
:: build_deploy_msys2.bat).

set "VCPKG_ROOT=D:\Project\Out\vcpkg"

:: CMake / Ninja — absolute paths; prepended to PATH if the exe exists.
set "CMAKE_DIR=C:\Qt\Tools\CMake_64\bin"
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

:: Qt install prefix — MUST be the MSVC Qt kit (NOT MSYS2's C:\msys64\mingw64).
:: If you mix this with MSYS2's prefix, cl.exe will see GCC headers and blow up
:: with thousands of __asm__ / __declspec(nothrow) syntax errors.
set "QT_DIR=C:\Qt\6.7.1\msvc2019_64"

set "MSBASE_ENV_LOADED=msvc"

echo ==== set_env (MSVC) applied ====
echo   VCPKG_ROOT = %VCPKG_ROOT%
echo   CMAKE_DIR  = %CMAKE_DIR%
echo   NINJA_DIR  = %NINJA_DIR%
echo   QT_DIR     = %QT_DIR%
echo ==================================
