@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%set_env.bat"

:: ----- Generate proto stubs (idempotent) -----
if not exist "%SCRIPT_DIR%proto\test_service.pb.h" (
    call "%SCRIPT_DIR%proto\generate_stubs.bat"
    if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )
)

:: ----- Build service -----
set "SERVICE_BUILD=%SCRIPT_DIR%build"
if not exist "%SERVICE_BUILD%" mkdir "%SERVICE_BUILD%"
pushd "%SERVICE_BUILD%"
cmake -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\scripts\buildsystems\vcpkg.cmake" ..
if errorlevel 1 ( echo Service configure failed. & popd & exit /b 1 )
cmake --build . --config Release
if errorlevel 1 ( echo Service build failed. & popd & exit /b 1 )
popd

:: ----- Build client -----
set "CLIENT_BUILD=%SCRIPT_DIR%client\build"
if not exist "%CLIENT_BUILD%" mkdir "%CLIENT_BUILD%"
pushd "%CLIENT_BUILD%"
cmake -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\scripts\buildsystems\vcpkg.cmake" ..
if errorlevel 1 ( echo Client configure failed. & popd & exit /b 1 )
cmake --build . --config Release
if errorlevel 1 ( echo Client build failed. & popd & exit /b 1 )
popd

:: ----- Collect binaries + runtime DLLs into dist\ -----
:: The vcpkg toolchain deploys required DLLs (grpc, protobuf, openssl,
:: zlib, abseil, c-ares, re2, etc.) next to each .exe during the build.
:: We copy the whole Release folder so the binaries run from dist\.
set "DIST=%SCRIPT_DIR%dist"
if not exist "%DIST%" mkdir "%DIST%"
xcopy /Y /Q "%SERVICE_BUILD%\Release\*.exe"  "%DIST%\" >nul 2>&1
xcopy /Y /Q "%SERVICE_BUILD%\Release\*.dll"  "%DIST%\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\Release\*.exe"   "%DIST%\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\Release\*.dll"   "%DIST%\" >nul 2>&1

:: ----- Deploy Qt DLLs for the GUI client (if built) -----
if exist "%DIST%\test_service_gui.exe" (
    if defined QT_DIR (
        if exist "%QT_DIR%\bin\windeployqt.exe" (
            echo Running windeployqt for test_service_gui.exe ...
            "%QT_DIR%\bin\windeployqt.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw "%DIST%\test_service_gui.exe" >nul
        ) else (
            echo WARNING: windeployqt not found at %QT_DIR%\bin\windeployqt.exe
            echo          Qt DLLs will not be deployed; test_service_gui.exe may fail to start.
        )
    ) else (
        echo WARNING: QT_DIR is not set; skipping windeployqt.
    )
)

echo.
echo Build complete.  Binaries collected in: %DIST%
endlocal
