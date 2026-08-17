@echo off
:: Central environment for MinGW builds.
::
:: THESE VALUES ALWAYS OVERWRITE whatever is in the parent shell.
:: Edit them directly to match your machine.
::
:: Called by build_deploy_mingw.bat; do NOT mix with build_deploy.bat
:: (which uses set_env.bat + MSVC).

set "VCPKG_ROOT=D:\Project\Out\vcpkg"
set "VCPKG_TRIPLET=x64-mingw-dynamic"
set "MINGW_DIR=C:\Qt\Tools\mingw1120_64\bin"
set "NINJA_DIR=C:\Qt\Tools\Ninja"
set "CMAKE_DIR=C:\Qt\Tools\CMake_64\bin"
set "QT_DIR=C:\Qt\6.7.1\mingw_64"

if exist "%MINGW_DIR%\g++.exe"   set "PATH=%MINGW_DIR%;%PATH%"
if exist "%NINJA_DIR%\ninja.exe" set "PATH=%NINJA_DIR%;%PATH%"
if exist "%CMAKE_DIR%\cmake.exe" set "PATH=%CMAKE_DIR%;%PATH%"

set "MSBASE_ENV_LOADED=mingw"

echo ==== set_env (MinGW) applied ====
echo   VCPKG_ROOT    = %VCPKG_ROOT%
echo   VCPKG_TRIPLET = %VCPKG_TRIPLET%
echo   MINGW_DIR     = %MINGW_DIR%
echo   NINJA_DIR     = %NINJA_DIR%
echo   CMAKE_DIR     = %CMAKE_DIR%
echo   QT_DIR        = %QT_DIR%
echo ==================================
