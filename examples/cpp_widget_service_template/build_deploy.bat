@echo off
setlocal enabledelayedexpansion

:: ===================================================================
:: build_deploy.bat — Build MyWidgetService + MyWidgetServicePreview
::                    and collect all executables and runtime DLLs into deploy/
:: ===================================================================
::
:: Usage:
::   build_deploy.bat              Build Release (default)
::   build_deploy.bat debug        Build Debug
::   build_deploy.bat clean        Delete build + deploy folders
::
:: Prerequisites:
::   - Qt 6 installed (MSVC 2019 64-bit kit)
::   - vcpkg with librabbitmq and nlohmann-json installed
::   - Visual Studio 2019 Build Tools (or Community)
::
:: Output:
::   deploy/
::   ├── MyWidgetService.exe            Backend service
::   ├── MyWidgetServicePreview.exe     Widget UI preview
::   ├── service_config.json            Service configuration
::   ├── ui/ServiceUI.ui                Widget UI file
::   ├── GUIs/ServiceUI.ui              Deployed copy (for svc_api_get_gui_files)
::   ├── Qt6Core.dll, Qt6Widgets.dll... Qt runtime DLLs (via windeployqt)
::   ├── plugins/                       Qt platform plugins
::   └── rabbitmq.4.dll                 RabbitMQ client DLL
:: ===================================================================

:: ----- Configurable paths (edit these if your setup differs) -----
set "QT_DIR=C:\Qt\6.7.1\msvc2019_64"
set "QT_CMAKE_DIR=C:\Qt\Tools\CMake_64\bin"
set "VCPKG_ROOT=D:\Project\Out\vcpkg"
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat"

:: ----- Derived paths -----
set "SCRIPT_DIR=%~dp0"
set "WINDEPLOYQT=%QT_DIR%\bin\windeployqt6.exe"
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
if not exist "%QT_DIR%\bin\qmake.exe" (
    echo ERROR: Qt not found at %QT_DIR%
    echo        Edit QT_DIR in this script to point to your Qt MSVC installation.
    exit /b 1
)
if not exist "%WINDEPLOYQT%" (
    echo ERROR: windeployqt6.exe not found at %WINDEPLOYQT%
    exit /b 1
)
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
:: Also add Qt bin for windeployqt.
set "PATH=%QT_CMAKE_DIR%;%QT_DIR%\bin;%PATH%"

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
if exist "%BUILD_DIR%\%BUILD_TYPE%\MyWidgetService.exe"        set "EXE_DIR=%BUILD_DIR%\%BUILD_TYPE%"
if exist "%BUILD_DIR%\%BUILD_TYPE%\MyWidgetServicePreview.exe" set "EXE_DIR=%BUILD_DIR%\%BUILD_TYPE%"
echo   Exe location: %EXE_DIR%

:: Copy executables
set "FOUND_BACKEND=0"
if exist "%EXE_DIR%\MyWidgetService.exe" (
    copy /Y "%EXE_DIR%\MyWidgetService.exe" "%DEPLOY_DIR%\" >nul
    echo   Copied MyWidgetService.exe
    set "FOUND_BACKEND=1"
)
if exist "%EXE_DIR%\MyWidgetServicePreview.exe" (
    copy /Y "%EXE_DIR%\MyWidgetServicePreview.exe" "%DEPLOY_DIR%\" >nul
    echo   Copied MyWidgetServicePreview.exe
)

:: Copy service config
if exist "%SCRIPT_DIR%service_config.json" (
    copy /Y "%SCRIPT_DIR%service_config.json" "%DEPLOY_DIR%\" >nul
    echo   Copied service_config.json
)

:: Copy UI files
if exist "%SCRIPT_DIR%ui" (
    xcopy /E /I /Y /Q "%SCRIPT_DIR%ui" "%DEPLOY_DIR%\ui" >nul
    echo   Copied ui\
)

:: Copy GUIs folder (.ui file served by MyWidgetService via svc_api_get_gui_files)
if exist "%SCRIPT_DIR%GUIs" (
    xcopy /E /I /Y /Q "%SCRIPT_DIR%GUIs" "%DEPLOY_DIR%\GUIs" >nul
    echo   Copied GUIs\
)

:: ----- windeployqt: auto-deploy Qt DLLs and plugins -----
echo.
echo ===== Running windeployqt =====

:: Run on MyWidgetServicePreview (Qt Widgets app — pulls in Qt deps).
if exist "%DEPLOY_DIR%\MyWidgetServicePreview.exe" (
    set "DEPLOY_LOG=%TEMP%\windeployqt_%RANDOM%.log"
    "%WINDEPLOYQT%" ^
        --dir "%DEPLOY_DIR%" ^
        --no-translations ^
        --no-opengl-sw ^
        --no-system-d3d-compiler ^
        "%DEPLOY_DIR%\MyWidgetServicePreview.exe" > "!DEPLOY_LOG!" 2>&1
    if errorlevel 1 (
        echo WARNING: windeployqt returned errors. Details:
        type "!DEPLOY_LOG!"
    ) else (
        set /a DEPLOY_COUNT=0
        for /f %%a in ('type "!DEPLOY_LOG!" ^| find /c /v ""') do set /a DEPLOY_COUNT=%%a
        echo   Qt dependencies deployed successfully ^(!DEPLOY_COUNT! files^).
    )
    del "!DEPLOY_LOG!" 2>nul
)

:: ----- vcpkg DLLs (rabbitmq-c + transitive deps) -----
echo.
echo ===== Copying vcpkg runtime DLLs =====
if "!FOUND_BACKEND!"=="1" (
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
)

:: ----- Summary -----
echo.
echo ===== Build complete =====
echo.
echo   Build type:  %BUILD_TYPE%
echo   Output:      %DEPLOY_DIR%
echo.
echo   Executables:
if exist "%DEPLOY_DIR%\MyWidgetService.exe"        echo     MyWidgetService.exe            (backend service)
if exist "%DEPLOY_DIR%\MyWidgetServicePreview.exe"  echo     MyWidgetServicePreview.exe     (widget UI preview)
if not exist "%DEPLOY_DIR%\MyWidgetService.exe" (
    echo     [MyWidgetService.exe not built — backend dependencies may be missing]
)
echo.
echo   To run the backend:
echo     cd %DEPLOY_DIR%
echo     MyWidgetService.exe
echo.
echo   To preview the Widget UI:
echo     cd %DEPLOY_DIR%
echo     MyWidgetServicePreview.exe                     (stub mode - mock responses)
echo     MyWidgetServicePreview.exe --live              (live mode - real RabbitMQ)
echo     MyWidgetServicePreview.exe --live --broker host:port
echo.

endlocal
