@echo off
setlocal enabledelayedexpansion

:: ===================================================================
:: build_wasm.bat — Build the Widget Shell WASM binary and deploy
:: ===================================================================
::
:: Usage:
::   build_wasm.bat              Build Release (default)
::   build_wasm.bat debug        Build Debug
::   build_wasm.bat clean        Delete WASM build folder
::
:: Prerequisites:
::   - Qt 6.5+ with wasm_singlethread target (must include Widgets + UiTools)
::   - Emscripten matching your Qt version (e.g., 3.1.50 for Qt 6.7.1)
::   - CMake 3.21+ and Ninja build system (both bundled with Qt)
::
:: Output:
::   ../web/widget-shell/
::   ├── widgetshell.wasm     WASM binary
::   └── widgetshell.js       Emscripten JS loader
:: ===================================================================

:: ----- Configurable paths (edit these if your setup differs) -----
set "QT_WASM_DIR=C:\Qt\6.7.1\wasm_singlethread"
set "QT_HOST_DIR=C:\Qt\6.7.1\msvc2019_64"
set "QT_CMAKE_DIR=C:\Qt\Tools\CMake_64\bin"
set "QT_NINJA_DIR=C:\Qt\Tools\Ninja"
set "EMSDK_DIR=D:\Project\robot\github\emsdk"

:: ----- Derived paths (strip trailing backslash from %~dp0) -----
set "SCRIPT_DIR=%~dp0"
if "!SCRIPT_DIR:~-1!"=="\" set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"
set "BUILD_DIR=!SCRIPT_DIR!\build\wasm"
set "EMSCRIPTEN_DIR=!EMSDK_DIR!\upstream\emscripten"
set "DEPLOY_DIR=!SCRIPT_DIR!\..\web\widget-shell"

:: ----- Parse arguments -----
set "BUILD_TYPE=Release"

if /I "%~1"=="debug" (
    set "BUILD_TYPE=Debug"
)
if /I "%~1"=="clean" (
    echo Cleaning WASM build folder...
    if exist "!BUILD_DIR!" rd /s /q "!BUILD_DIR!"
    echo Done.
    exit /b 0
)

:: ----- Validate prerequisites -----
if not exist "%QT_WASM_DIR%\bin\qt-cmake.bat" (
    echo ERROR: Qt WASM kit not found at %QT_WASM_DIR%
    echo        Edit QT_WASM_DIR in this script.
    echo        Install via Qt Maintenance Tool: Qt ^> 6.x ^> WebAssembly
    exit /b 1
)
if not exist "%QT_HOST_DIR%\bin\qmake.exe" (
    echo ERROR: Qt host kit not found at %QT_HOST_DIR%
    echo        Edit QT_HOST_DIR in this script ^(needed for moc/rcc/uic^).
    exit /b 1
)
if not exist "!EMSCRIPTEN_DIR!\emcc.bat" (
    echo ERROR: Emscripten not found at !EMSCRIPTEN_DIR!
    echo        Edit EMSDK_DIR in this script.
    exit /b 1
)

:: ----- Setup Emscripten environment directly -----
echo.
echo ===== Setting up Emscripten =====

:: Add emscripten + Qt CMake + Ninja to PATH
set "PATH=!EMSCRIPTEN_DIR!;!EMSDK_DIR!;%QT_CMAKE_DIR%;%QT_NINJA_DIR%;!PATH!"

:: Set EMSDK_PYTHON to emsdk's bundled Python (system Python may lack modules)
set "EMSDK=!EMSDK_DIR!"
if not defined EMSDK_PYTHON (
    for /f "delims=" %%P in ('dir /b /s "!EMSDK_DIR!\python\python.exe" 2^>nul') do (
        set "EMSDK_PYTHON=%%P"
    )
)
if not defined EMSDK_PYTHON set "EMSDK_PYTHON=python"

echo   EMSDK=!EMSDK!
echo   EMSDK_PYTHON=!EMSDK_PYTHON!

:: Verify emcc works
"!EMSDK_PYTHON!" -E "!EMSCRIPTEN_DIR!\emcc.py" --version >nul 2>&1
if errorlevel 1 (
    echo   WARNING: emcc verification failed — build may still work via CMake.
) else (
    echo   emcc verified OK
)

:: ----- Configure -----
echo.
echo ===== Configuring Widget Shell WASM Build [!BUILD_TYPE!] =====
echo   Qt WASM: %QT_WASM_DIR%
echo   Qt Host: %QT_HOST_DIR%
echo.

:: Emscripten requires Ninja (not Visual Studio generator).
set "QT_TOOLCHAIN=!QT_WASM_DIR!\lib\cmake\Qt6\qt.toolchain.cmake"
set "EM_TOOLCHAIN=!EMSCRIPTEN_DIR!\cmake\Modules\Platform\Emscripten.cmake"

cmake -G Ninja -DCMAKE_MAKE_PROGRAM="%QT_NINJA_DIR%\ninja.exe" -DCMAKE_TOOLCHAIN_FILE="!QT_TOOLCHAIN!" -DQT_CHAINLOAD_TOOLCHAIN_FILE="!EM_TOOLCHAIN!" -B "!BUILD_DIR!" -S "!SCRIPT_DIR!" -DQT_HOST_PATH="%QT_HOST_DIR%" -DCMAKE_BUILD_TYPE=!BUILD_TYPE!
if errorlevel 1 (
    echo ERROR: CMake configuration failed.
    exit /b 1
)

:: ----- Build -----
echo.
echo ===== Building Widget Shell WASM =====

:: If .js exists but .wasm is missing, force a relink.
if exist "!BUILD_DIR!\widgetshell.js" if not exist "!BUILD_DIR!\widgetshell.wasm" (
    echo   .wasm missing but .js exists — forcing relink...
    del "!BUILD_DIR!\widgetshell.js" 2>nul
)

cmake --build "!BUILD_DIR!" --parallel
if errorlevel 1 (
    echo ERROR: WASM build failed.
    exit /b 1
)

:: ----- Deploy to web/widget-shell/ -----
echo.
echo ===== Deploying to web/widget-shell/ =====

:: Find output files (Ninja: directly in build dir, VS: in Release/ subdir)
set "WASM_DIR=!BUILD_DIR!"
if exist "!BUILD_DIR!\!BUILD_TYPE!\widgetshell.wasm" set "WASM_DIR=!BUILD_DIR!\!BUILD_TYPE!"

if not exist "!WASM_DIR!\widgetshell.wasm" (
    echo ERROR: widgetshell.wasm not found in !WASM_DIR!
    echo        Check build output above for errors.
    exit /b 1
)

:: Create deploy directory if it doesn't exist
if not exist "!DEPLOY_DIR!" mkdir "!DEPLOY_DIR!"

:: Delete existing files first to avoid Windows case-insensitive overwrite issues
del "!DEPLOY_DIR!\widgetshell.wasm" 2>nul
del "!DEPLOY_DIR!\widgetshell.js" 2>nul
copy /Y "!WASM_DIR!\widgetshell.wasm" "!DEPLOY_DIR!\" >nul
echo   Copied widgetshell.wasm
copy /Y "!WASM_DIR!\widgetshell.js" "!DEPLOY_DIR!\" >nul
echo   Copied widgetshell.js

:: ----- Summary -----
echo.
echo ===== Widget Shell WASM build complete =====
echo.
echo   Output: web/widget-shell/
echo     widgetshell.wasm
echo     widgetshell.js
echo.

endlocal
