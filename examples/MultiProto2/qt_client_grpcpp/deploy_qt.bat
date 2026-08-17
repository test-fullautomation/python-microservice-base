@echo off
REM Bundle .exe + Qt DLLs + vcpkg DLLs + MinGW runtime into deploy\.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BUILD_DIR=%SCRIPT_DIR%\build"
set "DEPLOY_DIR=%SCRIPT_DIR%\deploy"
set "EXE_NAME=multi_proto2_qt_gui.exe"

if not exist "%BUILD_DIR%\%EXE_NAME%" (
    echo [deploy] ERROR: %BUILD_DIR%\%EXE_NAME% not found.  Run build_qt.bat first.
    exit /b 1
)
if not defined QT_DIR set "QT_DIR=C:\Qt\6.11.0\mingw_64"
REM windeployqt presence is checked later via the multi-name fallback loop;
REM Qt 6.5-6.7 ship windeployqt-qt6.exe, 6.8+ ship windeployqt6.exe, and
REM the generic windeployqt.exe is in every variant.

if exist "%DEPLOY_DIR%" rmdir /s /q "%DEPLOY_DIR%"
mkdir "%DEPLOY_DIR%"

echo [deploy] Copying %EXE_NAME%
copy /y "%BUILD_DIR%\%EXE_NAME%" "%DEPLOY_DIR%\" >nul

REM windeployqt name varies by Qt version: windeployqt-qt6 (6.5-6.7),
REM windeployqt6 (6.8+), or generic windeployqt.exe.
set "WINDEPLOYQT="
for %%E in (windeployqt-qt6.exe windeployqt6.exe windeployqt.exe) do (
    if not defined WINDEPLOYQT if exist "%QT_DIR%\bin\%%E" set "WINDEPLOYQT=%QT_DIR%\bin\%%E"
)
if not defined WINDEPLOYQT (
    echo [deploy] ERROR: no windeployqt found in %QT_DIR%\bin.  GUI exe will fail at runtime.
    exit /b 1
)
echo [deploy] windeployqt - %WINDEPLOYQT% - auto-detect Qt DLLs from exe PE header
"%WINDEPLOYQT%" --no-translations --no-system-d3d-compiler --no-opengl-sw "%DEPLOY_DIR%\%EXE_NAME%"
if errorlevel 1 ( echo [deploy] windeployqt failed. & exit /b 1 )

set "VCPKG_BIN=%BUILD_DIR%\vcpkg_installed\x64-mingw-qt\bin"
echo [deploy] Copying vcpkg runtime DLLs
for %%F in (libabseil_dll.dll libcares.dll libcrypto-3-x64.dll libprotobuf.dll libprotobuf-lite.dll libre2.dll libssl-3-x64.dll libzlib1.dll legacy.dll) do (
    if exist "%VCPKG_BIN%\%%F" copy /y "%VCPKG_BIN%\%%F" "%DEPLOY_DIR%\" >nul
)

echo.
echo [deploy] Bundle ready at %DEPLOY_DIR%
dir /b "%DEPLOY_DIR%"
endlocal
