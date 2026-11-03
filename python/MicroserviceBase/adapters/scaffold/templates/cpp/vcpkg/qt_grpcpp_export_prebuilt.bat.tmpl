@echo off
REM Package vcpkg artifacts so other devs build without rebuilding grpc/protobuf.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BUILD_DIR=%SCRIPT_DIR%\build"
set "INSTALLED_PARENT=%BUILD_DIR%\vcpkg_installed"
set "INSTALLED=%INSTALLED_PARENT%\x64-mingw-qt"
set "OUT_DIR=%SCRIPT_DIR%\prebuilt"

if not exist "%INSTALLED%" (
    echo [export] ERROR: %INSTALLED% not found.  Run build_qt.bat first.
    exit /b 1
)
set "TAR_EXE=%SystemRoot%\System32\tar.exe"
if not exist "%TAR_EXE%" (
    echo [export] ERROR: %TAR_EXE% not found.  Need Windows 10 1803+.
    exit /b 1
)

if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%"

REM Pack x64-mingw-qt + only x64-windows/tools/grpc/ (host grpc_cpp_plugin).
REM Skip x64-windows/tools/protobuf/ - protoc.exe is also at
REM x64-mingw-qt/tools/protobuf/ and CMakeLists pre-sets Protobuf_PROTOC_EXECUTABLE
REM there before find_package, so we don't need x64-windows for protoc.
set "PACK_ARGS=x64-mingw-qt"
if exist "%INSTALLED_PARENT%\x64-windows\tools\grpc" (
    set "PACK_ARGS=%PACK_ARGS% x64-windows\tools\grpc"
    echo [export] Including x64-windows\tools\grpc - host grpc_cpp_plugin.
)
echo [export] Packing installed tree
"%TAR_EXE%" -a -cf "%OUT_DIR%\vcpkg_installed_x64-mingw-qt.zip" -C "%INSTALLED_PARENT%" %PACK_ARGS%
if errorlevel 1 ( echo [export] tar failed. & exit /b 1 )

set "CACHE_PARENT=%LOCALAPPDATA%\vcpkg"
if exist "%CACHE_PARENT%\archives" (
    echo [export] Packing vcpkg binary cache
    "%TAR_EXE%" -a -cf "%OUT_DIR%\vcpkg_binary_cache.zip" -C "%CACHE_PARENT%" "archives"
)

echo.
echo [export] Done.
dir /b "%OUT_DIR%"
echo.
echo [export] Receiving PC:
echo   Method A: unzip vcpkg_installed_x64-mingw-qt.zip into qt_client_grpcpp\build\vcpkg_installed\
echo   Method B: unzip vcpkg_binary_cache.zip into %%LOCALAPPDATA%%\vcpkg\
echo   Then run build_qt.bat as usual.
endlocal
