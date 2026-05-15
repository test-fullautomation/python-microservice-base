@echo off
REM Pack the most-complete vcpkg artifacts from this project's build dirs
REM into prebuilt\vcpkg_installed_x64-mingw-qt.zip (and the binary cache).
REM Auto-detects the source build dir; override with --source <dir>.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "OUT_DIR=%SCRIPT_DIR%\prebuilt"

set "SRC="
if /i "%~1"=="--source" ( set "SRC=%~2"
) else if not "%~1"=="" ( set "SRC=%~1" )

if defined SRC (
    if not exist "!SRC!\vcpkg_installed\x64-mingw-qt\share\grpc" (
        echo [export] ERROR: !SRC!\vcpkg_installed\x64-mingw-qt incomplete.
        exit /b 1
    )
    set "INSTALLED_PARENT=!SRC!\vcpkg_installed"
    set "SRC_LABEL=user-specified"
) else (
    REM Auto-detect order matters: prefer the canonical CLI build dir
    REM (build-qt-vcpkg/) because it's most likely a clean from-source
    REM compile through our overlay-port (with gRPC_BUILD_CODEGEN=ON,
    REM grpc++_reflection, gcc 13 ICE patch).  Qt Creator kit dirs
    REM (build/Desktop_Qt_*/) often contain artifacts imported from a
    REM prebuilt zip OR built with different feature flags -- bad source
    REM for re-export since the receiver might miss reflection / codegen.
    if exist "%SCRIPT_DIR%\build-qt-vcpkg\vcpkg_installed\x64-mingw-qt\share\grpc" (
        set "INSTALLED_PARENT=%SCRIPT_DIR%\build-qt-vcpkg\vcpkg_installed"
        set "SRC_LABEL=server CLI (build-qt-vcpkg)"
    )
    if not defined INSTALLED_PARENT (
        if exist "%SCRIPT_DIR%\qt_client_grpcpp\build\vcpkg_installed\x64-mingw-qt\share\grpc" (
            set "INSTALLED_PARENT=%SCRIPT_DIR%\qt_client_grpcpp\build\vcpkg_installed"
            set "SRC_LABEL=client CLI (qt_client_grpcpp/build)"
        )
    )
    if not defined INSTALLED_PARENT (
        for /d %%D in ("%SCRIPT_DIR%\build\Desktop_Qt_*") do (
            if exist "%%D\vcpkg_installed\x64-mingw-qt\share\grpc" (
                if not defined INSTALLED_PARENT (
                    set "INSTALLED_PARENT=%%D\vcpkg_installed"
                    set "SRC_LABEL=Qt Creator (%%~nxD)"
                )
            )
        )
    )
    REM Sanity warning: if we picked a Qt Creator dir, that often means
    REM the user hasn't done a from-source CLI build yet -- their export
    REM may be re-packaging an imported zip rather than fresh artifacts.
    if defined INSTALLED_PARENT (
        echo !INSTALLED_PARENT! | findstr /i "Desktop_Qt_" >nul
        if not errorlevel 1 (
            echo [export] WARN: source is a Qt Creator kit build dir.
            echo [export]       If this came from an import_prebuilt.bat zip, the
            echo [export]       export will just re-pack what was imported.  For a
            echo [export]       fresh from-source build, run build_qt_vcpkg.bat first.
        )
    )
)

if not defined INSTALLED_PARENT (
    echo [export] ERROR: no vcpkg_installed\x64-mingw-qt found in any build dir.
    exit /b 1
)

set "TAR_EXE=%SystemRoot%\System32\tar.exe"
if not exist "%TAR_EXE%" ( echo [export] ERROR: %TAR_EXE% missing. & exit /b 1 )

echo [export] Source : !INSTALLED_PARENT!\x64-mingw-qt
echo [export] Origin : !SRC_LABEL!
if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%"

REM Pack x64-mingw-qt + only x64-windows/tools/grpc/ (host grpc_cpp_plugin
REM + sibling MSVC runtime DLLs).  protoc has its own copy at x64-mingw-qt/
REM tools/protobuf/ so x64-windows/tools/protobuf/ is redundant.
set "PACK_ARGS=x64-mingw-qt"
if exist "!INSTALLED_PARENT!\x64-windows\tools\grpc" (
    set "PACK_ARGS=!PACK_ARGS! x64-windows\tools\grpc"
    echo [export] Including x64-windows\tools\grpc - host grpc_cpp_plugin.
) else (
    echo [export] WARN: x64-windows\tools\grpc not found - codegen will fail.
)

echo [export] Packing zip...
"%TAR_EXE%" -a -cf "%OUT_DIR%\vcpkg_installed_x64-mingw-qt.zip" -C "!INSTALLED_PARENT!" !PACK_ARGS!
if errorlevel 1 ( echo [export] tar failed. & exit /b 1 )

set "CACHE_PARENT=%LOCALAPPDATA%\vcpkg"
if exist "%CACHE_PARENT%\archives" (
    echo [export] Packing vcpkg binary cache.
    "%TAR_EXE%" -a -cf "%OUT_DIR%\vcpkg_binary_cache.zip" -C "%CACHE_PARENT%" "archives"
)

echo.
echo [export] Done in %OUT_DIR%:
dir /b "%OUT_DIR%"
echo.
echo [export] Receiving PC: import_prebuilt.bat %%OUT_DIR%%\vcpkg_installed_x64-mingw-qt.zip
endlocal
