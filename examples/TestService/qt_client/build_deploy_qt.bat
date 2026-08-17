@echo off
:: Build + deploy the Qt-native client into a self-contained dist-qt/
:: folder.  Output:
::   dist-qt\test_service_qt_gui.exe          (the binary)
::   dist-qt\Qt6Core.dll, ...           (Qt runtime, via windeployqt)
::   dist-qt\platforms\qwindows.dll    (Qt platform plugin)
::   dist-qt\libstdc++-6.dll, ...       (MinGW runtime, via windeployqt --compiler-runtime)
::   dist-qt\run_test_service_qt_gui.bat      (launcher with QT_PLUGIN_PATH fallback)
::
:: The dist-qt/ folder is portable — copy it to another Windows machine
:: (no Qt install needed on the target) and run the launcher.

setlocal EnableDelayedExpansion

if not defined QT_DIR   set "QT_DIR=C:\Qt\6.11.0\mingw_64"
if not defined QT_TOOLS set "QT_TOOLS=C:\Qt\Tools"

set "EXE_NAME=test_service_qt_gui.exe"
set "BUILD=%~dp0build-qt"
set "DIST=%~dp0dist-qt"

:: ----- Step 1: configure + build (delegate to build_qt.bat) -----
call "%~dp0build_qt.bat"
if errorlevel 1 (
    echo Build failed; aborting deploy.
    exit /b 1
)

if not exist "%BUILD%\%EXE_NAME%" (
    echo ERROR: %BUILD%\%EXE_NAME% not found after build.
    exit /b 1
)

:: ----- Step 2: copy the binary -----
if not exist "%DIST%" mkdir "%DIST%"
xcopy /Y /Q "%BUILD%\%EXE_NAME%" "%DIST%\" >nul

:: ----- Step 3: windeployqt — copies Qt DLLs + platform plugin + MinGW runtime -----
set "WINDEPLOYQT="
for %%C in (windeployqt-qt6.exe windeployqt.exe) do (
    if not defined WINDEPLOYQT if exist "%QT_DIR%\bin\%%C" set "WINDEPLOYQT=%QT_DIR%\bin\%%C"
)
if defined WINDEPLOYQT (
    echo Running !WINDEPLOYQT! ...
    "!WINDEPLOYQT!" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\%EXE_NAME%"
    if errorlevel 1 (
        echo WARNING: windeployqt returned non-zero; the binary may still run if Qt is on PATH.
    )
) else (
    echo WARNING: windeployqt not found under %QT_DIR%\bin\
    echo          The exe will only run if Qt's bin and plugins folders are on PATH / QT_PLUGIN_PATH.
)

:: ----- Step 4: launcher .bat with QT_PLUGIN_PATH belt-and-braces fallback -----
> "%DIST%\run_test_service_qt_gui.bat" echo @echo off
>> "%DIST%\run_test_service_qt_gui.bat" echo if not defined QT_PLUGIN_PATH set "QT_PLUGIN_PATH=%QT_DIR%\plugins"
>> "%DIST%\run_test_service_qt_gui.bat" echo if not defined QML2_IMPORT_PATH set "QML2_IMPORT_PATH=%QT_DIR%\qml"
>> "%DIST%\run_test_service_qt_gui.bat" echo "%%~dp0%EXE_NAME%" %%*

echo.
echo Qt client deployed.  Output:
echo    %DIST%\%EXE_NAME%
echo Run via:
echo    %DIST%\run_test_service_qt_gui.bat
echo The dist-qt folder is portable to other Windows machines (no Qt install needed there).
endlocal
