@echo off
:: Pre-generate Qt6::Protobuf + Qt6::Grpc client stubs from every
:: .proto file in THIS folder.  Output lands next to the source .proto
:: (one .qpb.h/.cpp + one _client.grpc.qpb.h/.cpp per service).
::
:: This is a one-shot helper.  The CMake build runs the same protoc
:: invocations via qt_add_protobuf / qt_add_grpc, so you only need this
:: if you want browseable stubs in the proto/ folder alongside the .proto.
::
:: Honoured env vars:
::   QT_DIR       Qt install prefix.  Default: C:\Qt\6.11.0\mingw_64
::   PROTOC_DIR   Folder containing protoc.exe (defaults to MSYS2 / vcpkg / PATH).

setlocal EnableDelayedExpansion
if not defined QT_DIR set "QT_DIR=C:\Qt\6.11.0\mingw_64"

set "PROTO_DIR=%~dp0"
if "%PROTO_DIR:~-1%"=="\" set "PROTO_DIR=%PROTO_DIR:~0,-1%"

set "PROTOC="
if defined PROTOC_DIR if exist "%PROTOC_DIR%\protoc.exe" set "PROTOC=%PROTOC_DIR%\protoc.exe"
if not defined PROTOC if exist "C:\msys64\mingw64\bin\protoc.exe" set "PROTOC=C:\msys64\mingw64\bin\protoc.exe"
if not defined PROTOC if defined VCPKG_ROOT if exist "%VCPKG_ROOT%\installed\x64-windows\tools\protobuf\protoc.exe" set "PROTOC=%VCPKG_ROOT%\installed\x64-windows\tools\protobuf\protoc.exe"
if not defined PROTOC for /f "delims=" %%P in ('where protoc 2^>nul') do if not defined PROTOC set "PROTOC=%%P"

if not defined PROTOC (
    echo ERROR: protoc.exe not found.  Install MSYS2's mingw-w64-x86_64-protobuf or set PROTOC_DIR.
    exit /b 1
)

set "QTPB_PLUGIN=%QT_DIR%\bin\qtprotobufgen.exe"
set "QTGRPC_PLUGIN=%QT_DIR%\bin\qtgrpcgen.exe"
if not exist "%QTPB_PLUGIN%"   ( echo ERROR: qtprotobufgen.exe not found at %QTPB_PLUGIN%   & exit /b 1 )
if not exist "%QTGRPC_PLUGIN%" ( echo ERROR: qtgrpcgen.exe not found at %QTGRPC_PLUGIN%     & exit /b 1 )

echo Using:
echo   protoc        = %PROTOC%
echo   qtprotobufgen = %QTPB_PLUGIN%
echo   qtgrpcgen     = %QTGRPC_PLUGIN%
echo   PROTO_DIR     = %PROTO_DIR%
echo.

set "_any="
for %%P in ("%PROTO_DIR%\*.proto") do (
    set "_any=1"
    echo Generating stubs for %%~nxP
    "%PROTOC%" ^
        --plugin=protoc-gen-qtprotobuf="%QTPB_PLUGIN%" ^
        --qtprotobuf_out="%PROTO_DIR%" ^
        --proto_path="%PROTO_DIR%" ^
        "%%P"
    if errorlevel 1 ( echo Qt Protobuf generation failed for %%~nxP. & exit /b 1 )

    "%PROTOC%" ^
        --plugin=protoc-gen-qtgrpc="%QTGRPC_PLUGIN%" ^
        --qtgrpc_opt=GENERATE_PACKAGE_SUBFOLDERS=false ^
        --qtgrpc_out="%PROTO_DIR%" ^
        --proto_path="%PROTO_DIR%" ^
        "%%P"
    if errorlevel 1 ( echo Qt GRPC generation failed for %%~nxP. & exit /b 1 )
)

if not defined _any (
    echo WARN: no .proto files found in %PROTO_DIR%
    exit /b 1
)

echo.
echo Qt stubs generated in %PROTO_DIR%
endlocal
