@echo off
REM Build script for MultiProto2 qt_client_grpcpp.  See README.md.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "PROJECT_ROOT=%SCRIPT_DIR%\.."
set "BUILD_DIR=%SCRIPT_DIR%\build"

if not defined VCPKG_ROOT (
    echo [build_qt] ERROR: VCPKG_ROOT not set.  setx VCPKG_ROOT C:\vcpkg
    exit /b 1
)
if not defined QT_DIR (
    echo [build_qt] ERROR: QT_DIR not set.  setx QT_DIR C:\Qt\6.11.0\mingw_64
    exit /b 1
)
if not defined QT_MINGW_BIN set "QT_MINGW_BIN=C:\Qt\Tools\mingw1310_64\bin"
if not exist "%QT_MINGW_BIN%\g++.exe" (
    echo [build_qt] ERROR: Qt MinGW not found at %QT_MINGW_BIN%
    exit /b 1
)

REM One-time: copy upstream grpc port + apply our gcc 13 ICE patch.
if not exist "%PROJECT_ROOT%\ports\grpc\portfile.cmake" (
    call "%PROJECT_ROOT%\init_vcpkg_overlay.bat"
    if errorlevel 1 exit /b 1
)

set "PATH=%QT_MINGW_BIN%;%PATH%"
if exist "C:\Qt\Tools\CMake_64\bin\cmake.exe" set "PATH=C:\Qt\Tools\CMake_64\bin;%PATH%"
if exist "C:\Qt\Tools\Ninja\ninja.exe"        set "PATH=C:\Qt\Tools\Ninja;%PATH%"

REM Skip vcpkg install if USE_PREBUILT_VCPKG=1 and the install tree exists.
REM Goto-based control flow - chained `if A if B (...) else (...)` greedily
REM matches inner `if errorlevel 1 (..)` parens with the outer block, yielding
REM a stray `... was unexpected at this time` error.
if not "%USE_PREBUILT_VCPKG%"=="1" goto :do_vcpkg_install
if not exist "%BUILD_DIR%\vcpkg_installed\x64-mingw-qt\share\grpc" goto :do_vcpkg_install
echo [build_qt] USE_PREBUILT_VCPKG=1 + install tree present -^> skipping vcpkg install.
goto :after_vcpkg_install

:do_vcpkg_install
echo [build_qt] vcpkg install (slow on first run, instant after cache hit)...
"%VCPKG_ROOT%\vcpkg.exe" install ^
    --x-manifest-root="%SCRIPT_DIR%" ^
    --x-install-root="%BUILD_DIR%\vcpkg_installed" ^
    --overlay-triplets="%PROJECT_ROOT%\triplets" ^
    --overlay-ports="%PROJECT_ROOT%\ports" ^
    --triplet=x64-mingw-qt
if errorlevel 1 (
    echo [build_qt] vcpkg install failed.
    exit /b 1
)

:after_vcpkg_install

set "QT_MINGW_BIN_F=%QT_MINGW_BIN:\=/%"
set "QT_DIR_F=%QT_DIR:\=/%"
set "VCPKG_ROOT_F=%VCPKG_ROOT:\=/%"
set "SCRIPT_DIR_F=%SCRIPT_DIR:\=/%"
set "PROJECT_ROOT_F=%PROJECT_ROOT:\=/%"

if exist "%BUILD_DIR%\CMakeCache.txt" del /f /q "%BUILD_DIR%\CMakeCache.txt"
if exist "%BUILD_DIR%\CMakeFiles" rmdir /s /q "%BUILD_DIR%\CMakeFiles"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

REM When USE_PREBUILT_VCPKG=1, also tell the vcpkg toolchain to skip
REM its auto-install step (otherwise it re-runs `vcpkg install` at
REM configure time and ignores our prebuilt tree).
set "MANIFEST_FLAG="
if "%USE_PREBUILT_VCPKG%"=="1" set "MANIFEST_FLAG=-DVCPKG_MANIFEST_INSTALL=OFF"

cmake -S "%SCRIPT_DIR_F%" -B "%BUILD_DIR%" -G Ninja ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT_F%/scripts/buildsystems/vcpkg.cmake" ^
    -DVCPKG_TARGET_TRIPLET=x64-mingw-qt ^
    -DVCPKG_OVERLAY_TRIPLETS="%PROJECT_ROOT_F%/triplets" ^
    -DVCPKG_OVERLAY_PORTS="%PROJECT_ROOT_F%/ports" ^
    -DCMAKE_PREFIX_PATH="%QT_DIR_F%" ^
    -DCMAKE_C_COMPILER="%QT_MINGW_BIN_F%/gcc.exe" ^
    -DCMAKE_CXX_COMPILER="%QT_MINGW_BIN_F%/g++.exe" ^
    %MANIFEST_FLAG%
if errorlevel 1 ( echo [build_qt] cmake configure failed. & exit /b 1 )

cmake --build "%BUILD_DIR%" --parallel
if errorlevel 1 ( echo [build_qt] cmake build failed. & exit /b 1 )

echo.
echo [build_qt] OK -^> %BUILD_DIR%\multi_proto2_qt_gui.exe
endlocal
