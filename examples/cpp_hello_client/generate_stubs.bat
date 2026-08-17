@echo off
:: ===================================================================
:: generate_stubs.bat — Generate C++ gRPC stubs from a .proto file.
::
:: Run this ONCE after receiving the .proto from the service team.
:: The generated files go into gen/ and are regular C++ source that
:: you include in your project — no protoc needed for day-to-day builds.
::
:: Usage:
::   generate_stubs.bat                              (uses defaults)
::   generate_stubs.bat proto\hello.proto gen         (custom paths)
::
:: Prerequisites:
::   - protoc and grpc_cpp_plugin on PATH, or installed via vcpkg.
::   - If using vcpkg, set VCPKG_ROOT or pass the paths explicitly.
:: ===================================================================

setlocal enabledelayedexpansion

set "PROTO_FILE=%~1"
set "OUT_DIR=%~2"

if "%PROTO_FILE%"=="" set "PROTO_FILE=proto\hello.proto"
if "%OUT_DIR%"==""    set "OUT_DIR=gen"

:: ----- Find protoc and grpc_cpp_plugin -----
where protoc >nul 2>&1
if errorlevel 1 (
    :: Try vcpkg installed location
    if defined VCPKG_ROOT (
        set "PATH=!VCPKG_ROOT!\installed\x64-windows\tools\protobuf;!VCPKG_ROOT!\installed\x64-windows\tools\grpc;!PATH!"
    )
)

where protoc >nul 2>&1
if errorlevel 1 (
    echo ERROR: protoc not found in PATH.
    echo        Install via: vcpkg install protobuf:x64-windows grpc:x64-windows
    echo        Or set VCPKG_ROOT to your vcpkg installation.
    exit /b 1
)

where grpc_cpp_plugin >nul 2>&1
if errorlevel 1 (
    echo ERROR: grpc_cpp_plugin not found in PATH.
    echo        Install via: vcpkg install grpc:x64-windows
    exit /b 1
)

:: ----- Create output directory -----
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

:: ----- Get proto directory (for --proto_path) -----
for %%F in ("%PROTO_FILE%") do set "PROTO_DIR=%%~dpF"

echo.
echo ===== Generating C++ gRPC stubs =====
echo   Proto:   %PROTO_FILE%
echo   Output:  %OUT_DIR%
echo.

protoc ^
    --proto_path="%PROTO_DIR%" ^
    --cpp_out="%OUT_DIR%" ^
    --grpc_out="%OUT_DIR%" ^
    --plugin=protoc-gen-grpc="%~dp0..\..\..\..\vcpkg\installed\x64-windows\tools\grpc\grpc_cpp_plugin.exe" ^
    "%PROTO_FILE%"

if errorlevel 1 (
    :: Retry without explicit plugin path (might be on PATH already)
    protoc ^
        --proto_path="%PROTO_DIR%" ^
        --cpp_out="%OUT_DIR%" ^
        --grpc_out="%OUT_DIR%" ^
        --plugin=protoc-gen-grpc=grpc_cpp_plugin ^
        "%PROTO_FILE%"
)

if errorlevel 1 (
    echo.
    echo ERROR: protoc failed. Check the proto file and tool paths.
    exit /b 1
)

echo.
echo ===== Generated files =====
dir /b "%OUT_DIR%\*.h" "%OUT_DIR%\*.cc" 2>nul
echo.
echo Done. Include these files in your project and build normally.
echo You do NOT need protoc for day-to-day development after this step.

endlocal
