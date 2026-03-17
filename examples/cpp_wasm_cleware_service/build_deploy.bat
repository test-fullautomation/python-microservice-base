@echo off
setlocal enabledelayedexpansion

:: ===================================================================
:: build_deploy.bat — Build ServiceCleware backend and collect into deploy/
:: ===================================================================
::
:: Usage:
::   build_deploy.bat              Build Release (default)
::   build_deploy.bat debug        Build Debug
::   build_deploy.bat clean        Delete build + deploy folders

:: ----- Configurable paths -----
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

:: ----- Validate -----
if not exist "%VCPKG_TOOLCHAIN%" (
    echo ERROR: vcpkg not found at %VCPKG_ROOT%
    exit /b 1
)
if not exist "%VCVARS%" (
    echo ERROR: MSVC vcvars64.bat not found.
    exit /b 1
)

:: ----- MSVC -----
echo.
echo ===== Setting up MSVC environment =====
for %%F in ("%VCVARS%") do set "VCVARS_SHORT=%%~sF"
call "%VCVARS_SHORT%" >nul 2>&1

:: ----- Configure -----
echo.
echo ===== Configuring CMake [%BUILD_TYPE%] =====
cmake --preset %PRESET% "%SCRIPT_DIR%"
if errorlevel 1 (
    echo ERROR: CMake configuration failed.
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

if exist "%DEPLOY_DIR%" rd /s /q "%DEPLOY_DIR%"
mkdir "%DEPLOY_DIR%"

set "EXE_DIR=%BUILD_DIR%"
if exist "%BUILD_DIR%\%BUILD_TYPE%\ServiceCleware.exe" set "EXE_DIR=%BUILD_DIR%\%BUILD_TYPE%"

if exist "%EXE_DIR%\ServiceCleware.exe" (
    copy /Y "%EXE_DIR%\ServiceCleware.exe" "%DEPLOY_DIR%\" >nul
    echo   Copied ServiceCleware.exe
)

copy /Y "%SCRIPT_DIR%service_config.json" "%DEPLOY_DIR%\" >nul
echo   Copied service_config.json

if exist "%SCRIPT_DIR%GUIs" (
    xcopy /E /I /Y /Q "%SCRIPT_DIR%GUIs" "%DEPLOY_DIR%\GUIs" >nul
    echo   Copied GUIs\
)

if exist "%SCRIPT_DIR%libs" (
    xcopy /E /I /Y /Q "%SCRIPT_DIR%libs" "%DEPLOY_DIR%\libs" >nul
    echo   Copied libs\
)

:: vcpkg DLLs
set "VCPKG_BIN_ACTUAL=%VCPKG_BIN%"
for %%D in (rabbitmq.4.dll libssl-3-x64.dll libcrypto-3-x64.dll) do (
    if exist "!VCPKG_BIN_ACTUAL!\%%D" (
        copy /Y "!VCPKG_BIN_ACTUAL!\%%D" "%DEPLOY_DIR%\" >nul
        echo   Copied %%D
    )
)

echo.
echo ===== Build complete =====
echo.
echo   Backend: %DEPLOY_DIR%\ServiceCleware.exe
echo   WASM GUI: %DEPLOY_DIR%\GUIs\
echo.

endlocal
