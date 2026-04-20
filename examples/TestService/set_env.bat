@echo off
:: Central environment variables for this project.
::
:: Edit the defaults below, then every build script (build_deploy.bat,
:: proto\generate_stubs.bat, build_wasm.bat) picks them up automatically.
::
:: Variables already set in the shell or System Environment are NOT
:: overwritten — so CI and users with global config still work.

if not defined VCPKG_ROOT set "VCPKG_ROOT=D:\Project\Out\vcpkg"

:: CMake / Ninja — point these at your installs if they are NOT on PATH.
:: The block below prepends them to PATH so plain `cmake` / `ninja` work
:: from a vanilla cmd window (no Visual Studio Developer Prompt needed).
if not defined CMAKE_DIR set "CMAKE_DIR=C:\Qt\Tools\CMake_64\bin"
if not defined NINJA_DIR set "NINJA_DIR="

if exist "%CMAKE_DIR%\cmake.exe" set "PATH=%CMAKE_DIR%;%PATH%"
if defined NINJA_DIR if exist "%NINJA_DIR%\ninja.exe" set "PATH=%NINJA_DIR%;%PATH%"

:: MSVC compiler — call vcvars64.bat so cl.exe, link.exe, and Windows SDK
:: headers are available.  Skip if already initialised (VSCMD_ARG_TGT_ARCH
:: is set by vcvars itself) or from a Developer Command Prompt.
:: Point VS_DEV_CMD at the correct edition (Community / Professional / Enterprise).
if not defined VS_DEV_CMD set "VS_DEV_CMD=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not defined VSCMD_ARG_TGT_ARCH (
    if exist "%VS_DEV_CMD%" (
        call "%VS_DEV_CMD%" >nul
    )
)

:: Qt install prefix — needed by the Widgets GUI client (find_package(Qt6)).
:: Point to the Qt kit that matches your MSVC toolchain.
if not defined QT_DIR set "QT_DIR=C:\Qt\6.7.1\msvc2019_64"

