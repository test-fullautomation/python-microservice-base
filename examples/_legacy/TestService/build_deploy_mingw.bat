@echo off
:: MinGW variant of build_deploy.bat.
::
::   - Uses Ninja + MinGW g++ instead of MSBuild + cl.exe
::   - Uses vcpkg triplet x64-mingw-dynamic
::   - Points QT_DIR at the Qt MinGW kit
::
:: All paths come from set_env_mingw.bat (edit that file for your machine).
::
:: First-time vcpkg install for the mingw triplet can take 20-60 min
:: (ports compile from source).  Pre-seed with:
::     "%VCPKG_ROOT%\vcpkg" install grpc:x64-mingw-dynamic protobuf:x64-mingw-dynamic curl:x64-mingw-dynamic
setlocal

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%set_env_mingw.bat"

where g++ >nul 2>&1
if errorlevel 1 ( echo ERROR: g++ not found.  Check MINGW_DIR in set_env_mingw.bat & exit /b 1 )
where ninja >nul 2>&1
if errorlevel 1 ( echo ERROR: ninja not found.  Check NINJA_DIR in set_env_mingw.bat & exit /b 1 )

:: Verify the mingw-dynamic vcpkg triplet actually has grpc installed.
:: Without this, find_package falls back to the x64-windows (MSVC) prefix
:: and the link fails with MSVC-only flags like '-ignore:4221'.
if not exist "%VCPKG_ROOT%\installed\%VCPKG_TRIPLET%\share\grpc" (
    echo.
    echo ERROR: vcpkg packages for triplet "%VCPKG_TRIPLET%" are not installed.
    echo.
    echo        Run this once (first time can take 20-60 min^):
    echo.
    echo          set VCPKG_DEFAULT_TRIPLET=%VCPKG_TRIPLET%
    echo          "%VCPKG_ROOT%\vcpkg" install grpc:%VCPKG_TRIPLET% protobuf:%VCPKG_TRIPLET% curl:%VCPKG_TRIPLET%
    echo.
    exit /b 1
)

:: ----- Generate proto stubs (FORCE regenerate with MinGW protoc) -----
:: Proto stubs are toolchain-ABI-sensitive: stubs produced by a different
:: toolchain's protoc won't compile against this toolchain's protobuf
:: headers.  Always regenerate so they match the active install.
del /q "%SCRIPT_DIR%proto\test_service.pb.h"       >nul 2>&1
del /q "%SCRIPT_DIR%proto\test_service.pb.cc"      >nul 2>&1
del /q "%SCRIPT_DIR%proto\test_service.grpc.pb.h"  >nul 2>&1
del /q "%SCRIPT_DIR%proto\test_service.grpc.pb.cc" >nul 2>&1
call "%SCRIPT_DIR%proto\generate_stubs.bat"
if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )

:: ----- Build service (Ninja + MinGW) -----
set "SERVICE_BUILD=%SCRIPT_DIR%build-mingw"
if not exist "%SERVICE_BUILD%" mkdir "%SERVICE_BUILD%"
pushd "%SERVICE_BUILD%"
cmake -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\scripts\buildsystems\vcpkg.cmake" ^
      -DVCPKG_TARGET_TRIPLET=%VCPKG_TRIPLET% ^
      ..
if errorlevel 1 ( echo Service configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Service build failed. & popd & exit /b 1 )
popd

:: ----- Build client (Ninja + MinGW) -----
set "QT_PREFIX_ARG="
if defined QT_DIR set "QT_PREFIX_ARG=-DCMAKE_PREFIX_PATH=%QT_DIR%"

set "CLIENT_BUILD=%SCRIPT_DIR%client\build-mingw"
if not exist "%CLIENT_BUILD%" mkdir "%CLIENT_BUILD%"
pushd "%CLIENT_BUILD%"
cmake -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\scripts\buildsystems\vcpkg.cmake" ^
      -DVCPKG_TARGET_TRIPLET=%VCPKG_TRIPLET% ^
      %QT_PREFIX_ARG% ^
      ..
if errorlevel 1 ( echo Client configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Client build failed. & popd & exit /b 1 )
popd

:: ----- Collect binaries + runtime DLLs into dist-mingw\ -----
set "DIST=%SCRIPT_DIR%dist-mingw"
if not exist "%DIST%" mkdir "%DIST%"
xcopy /Y /Q "%SERVICE_BUILD%\*.exe" "%DIST%\" >nul 2>&1
xcopy /Y /Q "%SERVICE_BUILD%\*.dll" "%DIST%\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\*.exe"  "%DIST%\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\*.dll"  "%DIST%\" >nul 2>&1

:: MinGW C++ runtime libs come from MINGW_DIR, not vcpkg.
if defined MINGW_DIR (
    for %%L in (libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll) do (
        if exist "%MINGW_DIR%\%%L" copy /Y "%MINGW_DIR%\%%L" "%DIST%\" >nul
    )
)

:: ----- Deploy Qt runtime for the GUI (Qt6*.dll, platforms\, styles\) -----
if exist "%DIST%\test_service_gui.exe" (
    if defined QT_DIR (
        if exist "%QT_DIR%\bin\windeployqt.exe" (
            echo Running windeployqt for test_service_gui.exe ...
            "%QT_DIR%\bin\windeployqt.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\test_service_gui.exe" >nul
        ) else (
            echo WARNING: windeployqt not found at %QT_DIR%\bin\windeployqt.exe
        )
    ) else (
        echo WARNING: QT_DIR is not set; skipping windeployqt.
    )
)

echo.
echo MinGW build complete.  Binaries + runtime DLLs collected in: %DIST%
endlocal
