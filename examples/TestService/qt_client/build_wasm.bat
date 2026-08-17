@echo off
setlocal enabledelayedexpansion
:: Build the qt_client/ project as a multi-threaded WebAssembly module
:: against the Qt 6 WebAssembly kit.
::
:: Required env vars:
::   QT_WASM_DIR     Qt for WebAssembly install
::                   e.g. C:\Qt\6.11.0\wasm_multithread
::   QT_HOST_DIR     Matching desktop Qt install (same Qt version)
::                   e.g. C:\Qt\6.11.0\mingw_64
::                   Qt's WASM build needs a host Qt for moc/rcc tooling.
::   EMSDK_DIR       emsdk root (e.g. D:\Project\robot\github\emsdk)
::                   Must match the Emscripten version Qt was built against.
::
:: Optional:
::   QT_CMAKE_DIR    Qt-bundled CMake (default C:\Qt\Tools\CMake_64\bin)
::   QT_NINJA_DIR    Qt-bundled Ninja (default C:\Qt\Tools\Ninja)
::   EMSDK_PYTHON    emsdk-bundled Python (auto-detected under %EMSDK_DIR%\python)
::                   emcc.bat falls back to system Python which usually fails
::                   with "ModuleNotFoundError: No module named 'tools'".
::
:: Usage:
::   build_wasm.bat              Build Release
::   build_wasm.bat clean        Delete WASM build folder
set QT_WASM_DIR=C:\Qt\6.11.0\wasm_multithread
set QT_HOST_DIR=C:\Qt\6.11.0\mingw_64
set EMSDK_DIR=D:\Project\robot\github\emsdk
set "SCRIPT_DIR=%~dp0"
if "!SCRIPT_DIR:~-1!"=="\" set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"

if /I "%~1"=="clean" (
    if exist "!SCRIPT_DIR!\build-wasm" rd /s /q "!SCRIPT_DIR!\build-wasm"
    echo Cleaned. & exit /b 0
)

if not defined QT_WASM_DIR (
    echo ERROR: QT_WASM_DIR not set.
    echo Expected: C:\Qt\6.11.0\wasm_multithread  ^(or wasm_singlethread^)
    echo Install via Qt Maintenance Tool -^> Qt 6.x -^> WebAssembly.
    exit /b 1
)
if not defined QT_HOST_DIR (
    echo ERROR: QT_HOST_DIR not set.
    echo Expected: C:\Qt\6.11.0\mingw_64  ^(matching desktop kit, same Qt version^)
    echo qt-cmake's WASM build needs a host Qt for moc / rcc tooling.
    exit /b 1
)
if not defined EMSDK_DIR (
    echo ERROR: EMSDK_DIR not set.  Clone https://github.com/emscripten-core/emsdk
    echo and point EMSDK_DIR at the checkout.  Then activate the version Qt expects:
    echo     emsdk install ^<version^> ^&^& emsdk activate ^<version^>
    exit /b 1
)

if not exist "!QT_WASM_DIR!\lib\cmake\Qt6\Qt6Config.cmake" (
    echo ERROR: Qt6 not found at !QT_WASM_DIR!
    echo Expected: !QT_WASM_DIR!\lib\cmake\Qt6\Qt6Config.cmake
    exit /b 1
)
if not exist "!QT_WASM_DIR!\lib\cmake\Qt6Grpc\Qt6GrpcConfig.cmake" (
    echo ERROR: Qt GRPC module not installed in the WASM kit at !QT_WASM_DIR!
    echo Open Qt Maintenance Tool -^> Add or remove components, find your Qt 6.x,
    echo and tick under the WebAssembly target:
    echo     Qt GRPC
    echo     Qt Protobuf
    echo     Qt Protobuf Well Known Types
    exit /b 1
)
if not exist "!EMSDK_DIR!\upstream\emscripten\emcc.bat" (
    echo ERROR: emsdk not found at !EMSDK_DIR!\upstream\emscripten\
    echo Did you run 'emsdk install ^<version^>' and 'emsdk activate ^<version^>'?
    exit /b 1
)

if not defined QT_CMAKE_DIR set "QT_CMAKE_DIR=C:\Qt\Tools\CMake_64\bin"
if not defined QT_NINJA_DIR set "QT_NINJA_DIR=C:\Qt\Tools\Ninja"

if not exist "!QT_CMAKE_DIR!\cmake.exe" (
    echo ERROR: cmake not found at !QT_CMAKE_DIR!  ^(set QT_CMAKE_DIR^)
    exit /b 1
)
if not exist "!QT_NINJA_DIR!\ninja.exe" (
    echo ERROR: ninja not found at !QT_NINJA_DIR!  ^(set QT_NINJA_DIR^)
    exit /b 1
)

:: Auto-detect EMSDK_PYTHON if user didn't set one explicitly.
if not defined EMSDK_PYTHON (
    for /f "delims=" %%P in ('dir /b /ad /o-n "!EMSDK_DIR!\python" 2^>nul') do (
        if not defined EMSDK_PYTHON if exist "!EMSDK_DIR!\python\%%P\python.exe" (
            set "EMSDK_PYTHON=!EMSDK_DIR!\python\%%P\python.exe"
        )
    )
)
if not defined EMSDK_PYTHON (
    echo WARNING: EMSDK_PYTHON not found under !EMSDK_DIR!\python\.
    echo emcc will fall back to system Python which usually breaks
    echo with: ModuleNotFoundError: No module named 'tools'
)

set "EMSCRIPTEN_DIR=!EMSDK_DIR!\upstream\emscripten"
set "PATH=!EMSCRIPTEN_DIR!;!EMSDK_DIR!;!QT_CMAKE_DIR!;!QT_NINJA_DIR!;!PATH!"
set "EMSDK=!EMSDK_DIR!"

set "QT_TOOLCHAIN=!QT_WASM_DIR!\lib\cmake\Qt6\qt.toolchain.cmake"
set "EM_TOOLCHAIN=!EMSCRIPTEN_DIR!\cmake\Modules\Platform\Emscripten.cmake"
set "BUILD_DIR=!SCRIPT_DIR!\build-wasm"

if not exist "!BUILD_DIR!" mkdir "!BUILD_DIR!"

echo Using:
echo   QT_WASM_DIR   = !QT_WASM_DIR!
echo   QT_HOST_DIR   = !QT_HOST_DIR!
echo   EMSDK_DIR     = !EMSDK_DIR!
echo   EMSDK_PYTHON  = !EMSDK_PYTHON!
echo   BUILD_DIR     = !BUILD_DIR!
echo.

:: Qt6::ProtobufWellKnownTypes does find_file() for google/protobuf/*.proto
:: schemas; Emscripten's default CMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY
:: hides host paths, so the schemas are reported missing and find_package
:: aborts.  Point CMake at the MSYS2 protobuf install (where the .proto
:: files live next to protoc) and let it search host paths too.
set "PROTOC_HOST_ROOT_FOUND="
if defined PROTOC_HOST_ROOT (
    if exist "!PROTOC_HOST_ROOT!\include\google\protobuf\any.proto" set "PROTOC_HOST_ROOT_FOUND=!PROTOC_HOST_ROOT!"
)
if not defined PROTOC_HOST_ROOT_FOUND if exist "C:\msys64\mingw64\include\google\protobuf\any.proto" set "PROTOC_HOST_ROOT_FOUND=C:\msys64\mingw64"
if not defined PROTOC_HOST_ROOT_FOUND if defined VCPKG_ROOT if exist "%VCPKG_ROOT%\installed\x64-windows\include\google\protobuf\any.proto" set "PROTOC_HOST_ROOT_FOUND=%VCPKG_ROOT%\installed\x64-windows"

set "EXTRA_FIND_FLAGS="
if defined PROTOC_HOST_ROOT_FOUND (
    echo   PROTOC_HOST_ROOT = !PROTOC_HOST_ROOT_FOUND!
    set "EXTRA_FIND_FLAGS=-DCMAKE_FIND_ROOT_PATH=!PROTOC_HOST_ROOT_FOUND! -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=BOTH -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH"
) else (
    echo WARNING: host protoc include root not found.  Qt6::ProtobufWellKnownTypes
    echo will likely fail to find google/protobuf/*.proto schemas.  Install
    echo MSYS2 mingw-w64-x86_64-protobuf or set PROTOC_HOST_ROOT to a folder
    echo whose include/google/protobuf/ has any.proto, timestamp.proto, etc.
)

:: Call cmake directly (NOT qt-cmake.bat — on Windows it sets the Visual
:: Studio generator which Emscripten can't use, and qt-cmake doesn't
:: forward -G Ninja).
"!QT_CMAKE_DIR!\cmake.exe" -G Ninja ^
    -DCMAKE_MAKE_PROGRAM="!QT_NINJA_DIR!\ninja.exe" ^
    -DCMAKE_TOOLCHAIN_FILE="!QT_TOOLCHAIN!" ^
    -DQT_CHAINLOAD_TOOLCHAIN_FILE="!EM_TOOLCHAIN!" ^
    -DQT_HOST_PATH="!QT_HOST_DIR!" ^
    -DCMAKE_BUILD_TYPE=Release ^
    !EXTRA_FIND_FLAGS! ^
    -B "!BUILD_DIR!" -S "!SCRIPT_DIR!"
if errorlevel 1 ( echo CMake configure failed. & exit /b 1 )

"!QT_CMAKE_DIR!\cmake.exe" --build "!BUILD_DIR!" --parallel
if errorlevel 1 ( echo Build failed. & exit /b 1 )

echo.
echo WASM build complete.  Output:
echo   !BUILD_DIR!\test_service_qt_gui.wasm
echo   !BUILD_DIR!\test_service_qt_gui.js
echo   !BUILD_DIR!\test_service_qt_gui.html
echo   !BUILD_DIR!\qtloader.js
echo.
echo Serve with:    serve_wasm.bat
echo Then open:     http://127.0.0.1:8000/test_service_qt_gui.html
endlocal
