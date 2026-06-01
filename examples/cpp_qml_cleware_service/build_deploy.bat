@echo off
setlocal enabledelayedexpansion

:: ===================================================================
:: build_deploy.bat — Build ServiceCleware + ServiceClewarePreview
::                    and collect all executables and DLLs into deploy/
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
::   - Cleware USB DLL in libs/Windows/

:: ----- Configurable paths -----
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
    exit /b 1
)
if not exist "%WINDEPLOYQT%" (
    echo ERROR: windeployqt6.exe not found at %WINDEPLOYQT%
    exit /b 1
)
if not exist "%VCPKG_TOOLCHAIN%" (
    echo ERROR: vcpkg not found at %VCPKG_ROOT%
    exit /b 1
)
if not exist "%VCVARS%" (
    echo ERROR: MSVC vcvars64.bat not found.
    exit /b 1
)

:: ----- Setup MSVC environment -----
echo.
echo ===== Setting up MSVC environment =====
for %%F in ("%VCVARS%") do set "VCVARS_SHORT=%%~sF"
call "%VCVARS_SHORT%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Failed to initialize MSVC environment.
    exit /b 1
)

set "PATH=%QT_CMAKE_DIR%;%QT_DIR%\bin;%PATH%"

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
if exist "%BUILD_DIR%\%BUILD_TYPE%\ServiceCleware.exe"        set "EXE_DIR=%BUILD_DIR%\%BUILD_TYPE%"
if exist "%BUILD_DIR%\%BUILD_TYPE%\ServiceClewarePreview.exe"  set "EXE_DIR=%BUILD_DIR%\%BUILD_TYPE%"
echo   Exe location: %EXE_DIR%

:: Copy executables
set "FOUND_BACKEND=0"
if exist "%EXE_DIR%\ServiceCleware.exe" (
    copy /Y "%EXE_DIR%\ServiceCleware.exe" "%DEPLOY_DIR%\" >nul
    echo   Copied ServiceCleware.exe
    set "FOUND_BACKEND=1"
)
if exist "%EXE_DIR%\ServiceClewarePreview.exe" (
    copy /Y "%EXE_DIR%\ServiceClewarePreview.exe" "%DEPLOY_DIR%\" >nul
    echo   Copied ServiceClewarePreview.exe
)

:: Copy service config
if exist "%SCRIPT_DIR%service_config.json" (
    copy /Y "%SCRIPT_DIR%service_config.json" "%DEPLOY_DIR%\" >nul
    echo   Copied service_config.json
)

:: Copy QML files
if exist "%SCRIPT_DIR%qml" (
    xcopy /E /I /Y /Q "%SCRIPT_DIR%qml" "%DEPLOY_DIR%\qml" >nul
    echo   Copied qml\
)

:: Copy stubs
if exist "%SCRIPT_DIR%stubs" (
    xcopy /E /I /Y /Q "%SCRIPT_DIR%stubs" "%DEPLOY_DIR%\stubs" >nul
    echo   Copied stubs\
)

:: Copy GUIs folder
if exist "%SCRIPT_DIR%GUIs" (
    xcopy /E /I /Y /Q "%SCRIPT_DIR%GUIs" "%DEPLOY_DIR%\GUIs" >nul
    echo   Copied GUIs\
)

:: Copy Cleware USB libraries
if exist "%SCRIPT_DIR%libs" (
    xcopy /E /I /Y /Q "%SCRIPT_DIR%libs" "%DEPLOY_DIR%\libs" >nul
    echo   Copied libs\
)

:: ----- windeployqt -----
echo.
echo ===== Running windeployqt =====

if exist "%DEPLOY_DIR%\ServiceClewarePreview.exe" (
    set "DEPLOY_LOG=%TEMP%\windeployqt_%RANDOM%.log"
    "%WINDEPLOYQT%" ^
        --dir "%DEPLOY_DIR%" ^
        --qmldir "%SCRIPT_DIR%qml" ^
        --no-translations ^
        --no-opengl-sw ^
        --no-system-d3d-compiler ^
        "%DEPLOY_DIR%\ServiceClewarePreview.exe" > "!DEPLOY_LOG!" 2>&1
    if errorlevel 1 (
        echo WARNING: windeployqt returned errors.
        type "!DEPLOY_LOG!"
    ) else (
        set /a DEPLOY_COUNT=0
        for /f %%a in ('type "!DEPLOY_LOG!" ^| find /c /v ""') do set /a DEPLOY_COUNT=%%a
        echo   Qt dependencies deployed successfully ^(!DEPLOY_COUNT! files^).
    )
    del "!DEPLOY_LOG!" 2>nul
)

:: ----- vcpkg DLLs -----
echo.
echo ===== Copying vcpkg runtime DLLs =====
if "!FOUND_BACKEND!"=="1" (
    set "VCPKG_BIN_ACTUAL=%VCPKG_BIN%"
    if /I "%BUILD_TYPE%"=="Debug" (
        if exist "%VCPKG_ROOT%\installed\x64-windows\debug\bin" (
            set "VCPKG_BIN_ACTUAL=%VCPKG_ROOT%\installed\x64-windows\debug\bin"
        )
    )
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
if exist "%DEPLOY_DIR%\ServiceCleware.exe"        echo     ServiceCleware.exe          (backend service)
if exist "%DEPLOY_DIR%\ServiceClewarePreview.exe"  echo     ServiceClewarePreview.exe   (QML UI preview)
if not exist "%DEPLOY_DIR%\ServiceCleware.exe" (
    echo     [ServiceCleware.exe not built — backend dependencies may be missing]
)
echo.
echo   To run the backend:
echo     cd %DEPLOY_DIR%
echo     ServiceCleware.exe
echo.
echo   To preview the QML UI:
echo     cd %DEPLOY_DIR%
echo     ServiceClewarePreview.exe
echo.

endlocal
