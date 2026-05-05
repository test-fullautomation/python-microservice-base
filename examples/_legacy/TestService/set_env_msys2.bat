@echo off
:: Central environment for MSYS2 / MinGW builds.
::
:: Uses MSYS2's native MinGW packages (installed via pacman) instead of
:: vcpkg — more reliable MinGW story on Windows, since MSYS2 *is* the
:: native MinGW-w64 ecosystem.
::
:: One-time setup:
::   1. Install MSYS2 from https://www.msys2.org/ (default path: C:\msys64)
::   2. Install the required packages:
::        C:\msys64\usr\bin\pacman -S --needed ^
::           mingw-w64-x86_64-gcc ^
::           mingw-w64-x86_64-cmake ^
::           mingw-w64-x86_64-ninja ^
::           mingw-w64-x86_64-grpc ^
::           mingw-w64-x86_64-protobuf ^
::           mingw-w64-x86_64-curl ^
::           mingw-w64-x86_64-qt6-base ^
::           mingw-w64-x86_64-qt6-tools
::
:: THESE VALUES ALWAYS OVERWRITE whatever is in the parent shell.

set "MSYS2_ROOT=C:\msys64\mingw64"
set "QT_DIR=%MSYS2_ROOT%"

set "PATH=%MSYS2_ROOT%\bin;%PATH%"

set "MSBASE_ENV_LOADED=msys2"

echo ==== set_env (MSYS2) applied ====
echo   MSYS2_ROOT = %MSYS2_ROOT%
echo   QT_DIR     = %QT_DIR%
echo ==================================
