@echo off
:: MSYS2 variant of build_deploy.bat.
::
::   - Uses MSYS2's native MinGW toolchain (g++/cmake/ninja)
::   - Consumes MSYS2 pacman packages (grpc, protobuf, curl, Qt6)
::   - No vcpkg, no community-tier triplet gymnastics
::
:: Much more reliable than vcpkg+MinGW.  See set_env_msys2.bat for the
:: one-time pacman install.
setlocal

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%set_env_msys2.bat"

where g++   >nul 2>&1 || ( echo ERROR: g++ not found.   Check MSYS2_ROOT in set_env_msys2.bat & exit /b 1 )
where ninja >nul 2>&1 || ( echo ERROR: ninja not found. Install: pacman -S mingw-w64-x86_64-ninja & exit /b 1 )
where cmake >nul 2>&1 || ( echo ERROR: cmake not found. Install: pacman -S mingw-w64-x86_64-cmake & exit /b 1 )

:: Verify MSYS2 has gRPC installed.
if not exist "%MSYS2_ROOT%\share\grpc" (
    echo.
    echo ERROR: MSYS2 package mingw-w64-x86_64-grpc is not installed.
    echo.
    echo        From a cmd or MSYS2 shell:
    echo          C:\msys64\usr\bin\pacman -S --needed ^
    echo            mingw-w64-x86_64-grpc mingw-w64-x86_64-protobuf mingw-w64-x86_64-curl ^
    echo            mingw-w64-x86_64-qt6-base mingw-w64-x86_64-qt6-tools
    echo.
    exit /b 1
)

:: ----- Generate proto stubs (FORCE regenerate with MSYS2 protoc) -----
del /q "%SCRIPT_DIR%proto\test_service.pb.h"       >nul 2>&1
del /q "%SCRIPT_DIR%proto\test_service.pb.cc"      >nul 2>&1
del /q "%SCRIPT_DIR%proto\test_service.grpc.pb.h"  >nul 2>&1
del /q "%SCRIPT_DIR%proto\test_service.grpc.pb.cc" >nul 2>&1
call "%SCRIPT_DIR%proto\generate_stubs.bat"
if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )

:: ----- Build service (Ninja + MinGW from MSYS2) -----
set "SERVICE_BUILD=%SCRIPT_DIR%build-msys2"
if not exist "%SERVICE_BUILD%" mkdir "%SERVICE_BUILD%"
pushd "%SERVICE_BUILD%"
cmake -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_PREFIX_PATH="%MSYS2_ROOT%;%QT_DIR%" ^
      ..
if errorlevel 1 ( echo Service configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Service build failed. & popd & exit /b 1 )
popd

:: ----- Build client -----
set "CLIENT_BUILD=%SCRIPT_DIR%client\build-msys2"
if not exist "%CLIENT_BUILD%" mkdir "%CLIENT_BUILD%"
pushd "%CLIENT_BUILD%"
cmake -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_PREFIX_PATH="%MSYS2_ROOT%;%QT_DIR%" ^
      ..
if errorlevel 1 ( echo Client configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Client build failed. & popd & exit /b 1 )
popd

:: ----- Collect binaries + runtime DLLs into dist-msys2\ -----
set "DIST=%SCRIPT_DIR%dist-msys2"
if not exist "%DIST%" mkdir "%DIST%"
xcopy /Y /Q "%SERVICE_BUILD%\*.exe" "%DIST%\" >nul 2>&1
xcopy /Y /Q "%SERVICE_BUILD%\*.dll" "%DIST%\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\*.exe"  "%DIST%\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\*.dll"  "%DIST%\" >nul 2>&1

:: MSYS2 runtime + dependency DLLs.
if exist "%MSYS2_ROOT%\bin" (
    for %%L in (libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll zlib1.dll) do (
        if exist "%MSYS2_ROOT%\bin\%%L" copy /Y "%MSYS2_ROOT%\bin\%%L" "%DIST%\" >nul
    )
    for %%G in (libgrpc libprotobuf libabsl libcares libre2 libssl libcrypto libcurl libidn2 libintl libiconv libpsl libunistring libzstd libbrotli libnghttp2 libssh2) do (
        xcopy /Y /Q "%MSYS2_ROOT%\bin\%%G*.dll" "%DIST%\" >nul 2>&1
    )
)

:: ----- Deploy Qt runtime for the GUI (MSYS2 ships windeployqt with qt6-tools) -----
if exist "%DIST%\test_service_gui.exe" (
    if exist "%MSYS2_ROOT%\bin\windeployqt-qt6.exe" (
        echo Running windeployqt-qt6 for test_service_gui.exe ...
        "%MSYS2_ROOT%\bin\windeployqt-qt6.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\test_service_gui.exe" >nul
    ) else if exist "%MSYS2_ROOT%\bin\windeployqt.exe" (
        echo Running windeployqt for test_service_gui.exe ...
        "%MSYS2_ROOT%\bin\windeployqt.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\test_service_gui.exe" >nul
    ) else (
        echo WARNING: windeployqt not found in %MSYS2_ROOT%\bin
        echo          Install with:  pacman -S mingw-w64-x86_64-qt6-tools
    )
)

echo.
echo MSYS2 build complete.  Binaries + runtime DLLs collected in: %DIST%
endlocal
