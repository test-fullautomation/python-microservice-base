@echo off
setlocal enabledelayedexpansion

:: ===================================================================
:: build_deploy.bat — Build MyQtWasmService backend and collect
::                    executable and runtime DLLs into deploy/
:: ===================================================================
::
:: Usage:
::   build_deploy.bat              Build Release (default)
::   build_deploy.bat debug        Build Debug
::   build_deploy.bat clean        Delete build + deploy folders
::
:: Prerequisites:
::   - vcpkg with librabbitmq and nlohmann-json installed
::   - Visual Studio 2019 Build Tools (or Community)
::   - CppServiceBase library built (../cpp_service_base/build/)
::
:: Output:
::   deploy/
::   ├── MyQtWasmService.exe           Backend service
::   ├── service_config.json           Service configuration
::   ├── GUIs/                         WASM artifacts for web deployment
::   └── rabbitmq.4.dll + OpenSSL      RabbitMQ client DLLs
::
:: Note: The WASM GUI is tested directly in the browser via serve.bat
::       or build_wasm.sh — no desktop preview needed.
:: ===================================================================

:: ----- Configurable paths (edit these if your setup differs) -----
set "QT_CMAKE_DIR=C:\Qt\Tools\CMake_64\bin"
set "VCPKG_ROOT=D:\Project\Out\vcpkg"
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat"

:: ----- Derived paths -----
set "SCRIPT_DIR=%~dp0"
set "VCPKG_BIN=%VCPKG_ROOT%\installed\x64-windows\bin"
set "VCPKG_TOOLCHAIN=%VCPKG_ROOT%\scripts\buildsystems\vcpkg.cmake"

:: ----- Parse arguments -----
set "BUILD_TYPE=Release"
set "PRESET=release"

if /I "%~1"=="debug" (
    set "BUILD_TYPE=Debug"
    set "PRESET=default"
)
if /I "%~1"=="clean" (
    echo Cleaning build and deploy folders...
    if exist "%SCRIPT_DIR%build" rd /s /q "%SCRIPT_DIR%build"
    if exist "%SCRIPT_DIR%deploy" rd /s /q "%SCRIPT_DIR%deploy"
    echo Done.
    exit /b 0
)

set "BUILD_DIR=%SCRIPT_DIR%build\%PRESET%"
set "DEPLOY_DIR=%SCRIPT_DIR%deploy"

:: ----- Validate prerequisites -----
if not exist "%VCPKG_TOOLCHAIN%" (
    echo ERROR: vcpkg not found at %VCPKG_ROOT%
    echo        Edit VCPKG_ROOT in this script or run:
    echo          vcpkg install librabbitmq:x64-windows nlohmann-json:x64-windows
    exit /b 1
)
if not exist "%VCVARS%" (
    echo ERROR: MSVC vcvars64.bat not found.
    echo        Edit VCVARS in this script to point to your Visual Studio installation.
    exit /b 1
)

:: ----- Setup MSVC environment -----
echo.
echo ===== Setting up MSVC environment =====
:: Use short 8.3 path to avoid issues with parentheses in "Program Files (x86)"
for %%F in ("%VCVARS%") do set "VCVARS_SHORT=%%~sF"
call "%VCVARS_SHORT%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Failed to initialize MSVC environment.
    exit /b 1
)

:: Add Qt's CMake (3.27+) before system CMake to support preset version 3.
set "PATH=%QT_CMAKE_DIR%;%PATH%"

:: Verify cmake is available
where cmake >nul 2>&1
if errorlevel 1 (
    echo ERROR: cmake not found in PATH. Install CMake or use Qt's bundled cmake.
    exit /b 1
)
for /f "tokens=3" %%v in ('cmake --version 2^>nul ^| findstr /i "version"') do (
    echo   Using CMake %%v
)

:: ----- Configure -----
echo.
echo ===== Configuring CMake [%BUILD_TYPE%] =====
cmake --preset %PRESET% "%SCRIPT_DIR%"
if errorlevel 1 (
    echo.
    echo ERROR: CMake configuration failed.
    echo        Make sure vcpkg packages are installed:
    echo          %VCPKG_ROOT%\vcpkg install librabbitmq:x64-windows nlohmann-json:x64-windows
    echo        Make sure CppServiceBase is built:
    echo          cd ..\cpp_service_base ^&^& cmake -B build ^&^& cmake --build build
    exit /b 1
)

:: ----- Build -----
echo.
echo ===== Building =====
cmake --build "%BUILD_DIR%" --config %BUILD_TYPE%
if errorlevel 1 (
    echo ERROR: Build failed.
    exit /b 1
)

:: ----- Deploy -----
echo.
echo ===== Deploying to %DEPLOY_DIR% =====

:: Create deploy directory
if exist "%DEPLOY_DIR%" rd /s /q "%DEPLOY_DIR%"
mkdir "%DEPLOY_DIR%"

:: Find executables — Visual Studio generators put them under Debug/ or Release/
:: while Ninja puts them directly in the build dir.
set "EXE_DIR=%BUILD_DIR%"
if exist "%BUILD_DIR%\%BUILD_TYPE%\MyQtWasmService.exe" set "EXE_DIR=%BUILD_DIR%\%BUILD_TYPE%"
echo   Exe location: %EXE_DIR%

:: Copy backend executable
if exist "%EXE_DIR%\MyQtWasmService.exe" (
    copy /Y "%EXE_DIR%\MyQtWasmService.exe" "%DEPLOY_DIR%\" >nul
    echo   Copied MyQtWasmService.exe
) else (
    echo   WARNING: MyQtWasmService.exe not found — backend dependencies may be missing
)

:: Copy service config
if exist "%SCRIPT_DIR%service_config.json" (
    copy /Y "%SCRIPT_DIR%service_config.json" "%DEPLOY_DIR%\" >nul
    echo   Copied service_config.json
)

:: Copy GUIs folder (served by MyQtWasmService via svc_api_get_gui_files)
if exist "%SCRIPT_DIR%GUIs" (
    xcopy /E /I /Y /Q "%SCRIPT_DIR%GUIs" "%DEPLOY_DIR%\GUIs" >nul
    echo   Copied GUIs\
)

:: ----- vcpkg DLLs (rabbitmq-c + transitive deps) -----
echo.
echo ===== Copying vcpkg runtime DLLs =====
:: Use debug DLLs for Debug builds, release DLLs otherwise
set "VCPKG_BIN_ACTUAL=%VCPKG_BIN%"
if /I "%BUILD_TYPE%"=="Debug" (
    if exist "%VCPKG_ROOT%\installed\x64-windows\debug\bin" (
        set "VCPKG_BIN_ACTUAL=%VCPKG_ROOT%\installed\x64-windows\debug\bin"
    )
)
:: rabbitmq-c and its transitive dependencies (OpenSSL)
for %%D in (
    rabbitmq.4.dll
    libssl-3-x64.dll
    libcrypto-3-x64.dll
) do (
    if exist "!VCPKG_BIN_ACTUAL!\%%D" (
        copy /Y "!VCPKG_BIN_ACTUAL!\%%D" "%DEPLOY_DIR%\" >nul
        echo   Copied %%D
    ) else if exist "%VCPKG_BIN%\%%D" (
        copy /Y "%VCPKG_BIN%\%%D" "%DEPLOY_DIR%\" >nul
        echo   Copied %%D ^(release^)
    ) else (
        echo   WARNING: %%D not found
    )
)

:: ----- Summary -----
echo.
echo ===== Build complete =====
echo.
echo   Build type:  %BUILD_TYPE%
echo   Output:      %DEPLOY_DIR%
echo.
echo   To run the backend:
echo     cd %DEPLOY_DIR%
echo     MyQtWasmService.exe
echo.
echo   To test the WASM GUI in a browser:
echo     build_wasm.sh          (build WASM binary)
echo     serve.bat              (start local HTTP server)
echo.

endlocal
