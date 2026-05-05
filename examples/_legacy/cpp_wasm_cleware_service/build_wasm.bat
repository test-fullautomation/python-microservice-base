@echo off
setlocal enabledelayedexpansion

:: ===================================================================
:: build_wasm.bat — Build the Cleware Qt WASM GUI and copy to GUIs/
:: ===================================================================
::
:: Usage:
::   build_wasm.bat              Build Release (default)
::   build_wasm.bat debug        Build Debug
::   build_wasm.bat clean        Delete WASM build folder

:: ----- Configurable paths -----
set "QT_WASM_DIR=C:\Qt\6.7.1\wasm_singlethread"
set "QT_HOST_DIR=C:\Qt\6.7.1\msvc2019_64"
set "QT_CMAKE_DIR=C:\Qt\Tools\CMake_64\bin"
set "QT_NINJA_DIR=C:\Qt\Tools\Ninja"
set "EMSDK_DIR=D:\Project\robot\github\emsdk"

:: ----- Derived paths -----
set "SCRIPT_DIR=%~dp0"
if "!SCRIPT_DIR:~-1!"=="\" set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"
set "BUILD_DIR=!SCRIPT_DIR!\build\wasm"
set "EMSCRIPTEN_DIR=!EMSDK_DIR!\upstream\emscripten"

:: ----- Parse arguments -----
set "BUILD_TYPE=Release"

if /I "%~1"=="debug" set "BUILD_TYPE=Debug"
if /I "%~1"=="clean" (
    echo Cleaning WASM build folder...
    if exist "!BUILD_DIR!" rd /s /q "!BUILD_DIR!"
    echo Done.
    exit /b 0
)

:: ----- Validate prerequisites -----
if not exist "%QT_WASM_DIR%\bin\qt-cmake.bat" (
    echo ERROR: Qt WASM kit not found at %QT_WASM_DIR%
    exit /b 1
)
if not exist "%QT_HOST_DIR%\bin\qmake.exe" (
    echo ERROR: Qt host kit not found at %QT_HOST_DIR%
    exit /b 1
)
if not exist "!EMSCRIPTEN_DIR!\emcc.bat" (
    echo ERROR: Emscripten not found at !EMSCRIPTEN_DIR!
    exit /b 1
)

:: ----- Setup Emscripten -----
echo.
echo ===== Setting up Emscripten =====

set "PATH=!EMSCRIPTEN_DIR!;!EMSDK_DIR!;%QT_CMAKE_DIR%;%QT_NINJA_DIR%;!PATH!"

set "EMSDK=!EMSDK_DIR!"
if not defined EMSDK_PYTHON (
    for /f "delims=" %%P in ('dir /b /s "!EMSDK_DIR!\python\python.exe" 2^>nul') do (
        set "EMSDK_PYTHON=%%P"
    )
)
if not defined EMSDK_PYTHON set "EMSDK_PYTHON=python"

echo   EMSDK=!EMSDK!

:: ----- Configure -----
echo.
echo ===== Configuring Qt WASM Build [!BUILD_TYPE!] =====

set "QT_TOOLCHAIN=!QT_WASM_DIR!\lib\cmake\Qt6\qt.toolchain.cmake"
set "EM_TOOLCHAIN=!EMSCRIPTEN_DIR!\cmake\Modules\Platform\Emscripten.cmake"

cmake -G Ninja -DCMAKE_MAKE_PROGRAM="%QT_NINJA_DIR%\ninja.exe" -DCMAKE_TOOLCHAIN_FILE="!QT_TOOLCHAIN!" -DQT_CHAINLOAD_TOOLCHAIN_FILE="!EM_TOOLCHAIN!" -B "!BUILD_DIR!" -S "!SCRIPT_DIR!" -DQT_HOST_PATH="%QT_HOST_DIR%" -DCMAKE_BUILD_TYPE=!BUILD_TYPE!
if errorlevel 1 (
    echo ERROR: CMake configuration failed.
    exit /b 1
)

:: ----- Build -----
echo.
echo ===== Building WASM =====

if exist "!BUILD_DIR!\servicecleware_wasm.js" if not exist "!BUILD_DIR!\servicecleware_wasm.wasm" (
    echo   .wasm missing but .js exists — forcing relink...
    del "!BUILD_DIR!\servicecleware_wasm.js" 2>nul
)

cmake --build "!BUILD_DIR!" --parallel
if errorlevel 1 (
    echo ERROR: WASM build failed.
    exit /b 1
)

:: ----- Copy to GUIs/ -----
echo.
echo ===== Copying WASM output to GUIs/ =====

set "WASM_DIR=!BUILD_DIR!"
if exist "!BUILD_DIR!\!BUILD_TYPE!\servicecleware_wasm.wasm" set "WASM_DIR=!BUILD_DIR!\!BUILD_TYPE!"

if not exist "!WASM_DIR!\servicecleware_wasm.wasm" (
    echo ERROR: servicecleware_wasm.wasm not found in !WASM_DIR!
    exit /b 1
)

del "!SCRIPT_DIR!\GUIs\servicecleware_wasm.wasm" 2>nul
del "!SCRIPT_DIR!\GUIs\servicecleware_wasm.js" 2>nul
copy /Y "!WASM_DIR!\servicecleware_wasm.wasm" "!SCRIPT_DIR!\GUIs\" >nul
echo   Copied servicecleware_wasm.wasm
copy /Y "!WASM_DIR!\servicecleware_wasm.js" "!SCRIPT_DIR!\GUIs\" >nul
echo   Copied servicecleware_wasm.js

:: ----- Summary -----
echo.
echo ===== WASM build complete =====
echo.
echo   Output: GUIs/
echo     servicecleware_wasm.wasm
echo     servicecleware_wasm.js
echo.
echo   To test in browser:
echo     serve.bat
echo.

endlocal
