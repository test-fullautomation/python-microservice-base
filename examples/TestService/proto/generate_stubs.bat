@echo off
:: Generate C++ gRPC stubs from test_service.proto.
:: Run once, then both service and client can build without protoc.
setlocal enabledelayedexpansion

set "PROTO_DIR=%~dp0"
:: Remove trailing backslash
if "!PROTO_DIR:~-1!"=="\" set "PROTO_DIR=!PROTO_DIR:~0,-1!"

:: Pull VCPKG_ROOT from the central set_env.bat in the project root.
if exist "!PROTO_DIR!\..\set_env.bat" call "!PROTO_DIR!\..\set_env.bat"

:: ----- Find protoc and grpc_cpp_plugin -----
set "PROTOC="
set "GRPC_PLUGIN="

if defined VCPKG_ROOT (
    if exist "!VCPKG_ROOT!\installed\x64-windows\tools\protobuf\protoc.exe" (
        set "PROTOC=!VCPKG_ROOT!\installed\x64-windows\tools\protobuf\protoc.exe"
    )
    if exist "!VCPKG_ROOT!\installed\x64-windows\tools\grpc\grpc_cpp_plugin.exe" (
        set "GRPC_PLUGIN=!VCPKG_ROOT!\installed\x64-windows\tools\grpc\grpc_cpp_plugin.exe"
    )
)

if "!PROTOC!"=="" (
    for /f "delims=" %%P in ('where protoc 2^>nul') do set "PROTOC=%%P"
)
if "!GRPC_PLUGIN!"=="" (
    for /f "delims=" %%P in ('where grpc_cpp_plugin 2^>nul') do set "GRPC_PLUGIN=%%P"
)

if "!PROTOC!"=="" (
    echo ERROR: protoc not found.
    echo   Set VCPKG_ROOT or install: vcpkg install grpc:x64-windows protobuf:x64-windows
    exit /b 1
)
if "!GRPC_PLUGIN!"=="" (
    echo ERROR: grpc_cpp_plugin not found.
    echo   Set VCPKG_ROOT or install: vcpkg install grpc:x64-windows
    exit /b 1
)

echo protoc:          !PROTOC!
echo grpc_cpp_plugin: !GRPC_PLUGIN!
echo.
echo Generating stubs from test_service.proto into %PROTO_DIR% ...

"!PROTOC!" --proto_path="!PROTO_DIR!" --cpp_out="!PROTO_DIR!" --grpc_out="!PROTO_DIR!" --plugin=protoc-gen-grpc="!GRPC_PLUGIN!" "!PROTO_DIR!\test_service.proto"
if errorlevel 1 ( echo FAILED. & exit /b 1 )

echo.
echo Done. Generated files:
dir /b "!PROTO_DIR!\*.pb.h" "!PROTO_DIR!\*.pb.cc" 2>nul
echo.
echo Both service and client can now build without protoc.
endlocal
