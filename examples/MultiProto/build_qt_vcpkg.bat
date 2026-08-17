@echo off
REM Build MultiProto server using vcpkg + Qt MinGW (matches the
REM qt_client_grpcpp/ toolchain so client + server share one compiler ABI).
REM
REM To skip the vcpkg build entirely (use prebuilt artifacts shared by
REM another developer), set USE_PREBUILT_VCPKG=1 and unzip the prebuilt
REM tree into %BUILD_DIR%\vcpkg_installed\x64-mingw-qt\ first.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BUILD_DIR=%SCRIPT_DIR%\build-qt-vcpkg"

if not defined VCPKG_ROOT ( echo [build] ERROR: VCPKG_ROOT not set. & exit /b 1 )
if not defined QT_MINGW_BIN set "QT_MINGW_BIN=C:\Qt\Tools\mingw1310_64\bin"
if not exist "%QT_MINGW_BIN%\g++.exe" (
    echo [build] ERROR: Qt MinGW not found at %QT_MINGW_BIN%
    exit /b 1
)

if not exist "%SCRIPT_DIR%\ports\grpc\portfile.cmake" (
    call "%SCRIPT_DIR%\init_vcpkg_overlay.bat"
    if errorlevel 1 exit /b 1
)

set "PATH=%QT_MINGW_BIN%;%PATH%"
if exist "C:\Qt\Tools\CMake_64\bin\cmake.exe" set "PATH=C:\Qt\Tools\CMake_64\bin;%PATH%"
if exist "C:\Qt\Tools\Ninja\ninja.exe"        set "PATH=C:\Qt\Tools\Ninja;%PATH%"

REM ---- vcpkg install ------------------------------------------------------
REM Goto-based control flow - chained `if A if B (...) else (...)` greedily
REM matches inner `if errorlevel 1 (..)` parens with the outer block.
if not "%USE_PREBUILT_VCPKG%"=="1" goto :do_vcpkg_install
if not exist "%BUILD_DIR%\vcpkg_installed\x64-mingw-qt\share\grpc" goto :do_vcpkg_install
echo [build] USE_PREBUILT_VCPKG=1 + install tree present -^> skipping vcpkg install.
goto :after_vcpkg_install

:do_vcpkg_install
echo [build] vcpkg install (slow on first run, instant after cache hit)...
"%VCPKG_ROOT%\vcpkg.exe" install ^
    --x-manifest-root="%SCRIPT_DIR%" ^
    --x-install-root="%BUILD_DIR%\vcpkg_installed" ^
    --overlay-triplets="%SCRIPT_DIR%\triplets" ^
    --overlay-ports="%SCRIPT_DIR%\ports" ^
    --triplet=x64-mingw-qt
if errorlevel 1 (
    echo [build] vcpkg install failed.
    exit /b 1
)

:after_vcpkg_install

set "QT_MINGW_BIN_F=%QT_MINGW_BIN:\=/%"
set "VCPKG_ROOT_F=%VCPKG_ROOT:\=/%"
set "SCRIPT_DIR_F=%SCRIPT_DIR:\=/%"

if exist "%BUILD_DIR%\CMakeCache.txt" del /f /q "%BUILD_DIR%\CMakeCache.txt"
if exist "%BUILD_DIR%\CMakeFiles" rmdir /s /q "%BUILD_DIR%\CMakeFiles"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

set "MANIFEST_FLAG="
if "%USE_PREBUILT_VCPKG%"=="1" set "MANIFEST_FLAG=-DVCPKG_MANIFEST_INSTALL=OFF"

cmake -S "%SCRIPT_DIR_F%" -B "%BUILD_DIR%" -G Ninja ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT_F%/scripts/buildsystems/vcpkg.cmake" ^
    -DVCPKG_TARGET_TRIPLET=x64-mingw-qt ^
    -DVCPKG_OVERLAY_TRIPLETS="%SCRIPT_DIR_F%/triplets" ^
    -DVCPKG_OVERLAY_PORTS="%SCRIPT_DIR_F%/ports" ^
    -DCMAKE_C_COMPILER="%QT_MINGW_BIN_F%/gcc.exe" ^
    -DCMAKE_CXX_COMPILER="%QT_MINGW_BIN_F%/g++.exe" ^
    %MANIFEST_FLAG%
if errorlevel 1 ( echo [build] cmake configure failed. & exit /b 1 )

cmake --build "%BUILD_DIR%" --parallel
if errorlevel 1 ( echo [build] cmake build failed. & exit /b 1 )

echo.
echo [build] OK.  Built executables in %BUILD_DIR%:
dir /b "%BUILD_DIR%\*.exe" 2>nul
endlocal
