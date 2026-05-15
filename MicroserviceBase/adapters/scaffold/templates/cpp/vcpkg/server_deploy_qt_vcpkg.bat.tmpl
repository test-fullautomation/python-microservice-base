@echo off
REM Bundle server (and optional Qt client) built via vcpkg + Qt MinGW
REM into dist-qt-vcpkg\.  Self-contained: zip + copy to any Win x64 PC,
REM no Qt/vcpkg/MinGW install needed on target.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BUILD_DIR=%SCRIPT_DIR%\build-qt-vcpkg"
set "DIST=%SCRIPT_DIR%\dist-qt-vcpkg"
set "VCPKG_BIN=%BUILD_DIR%\vcpkg_installed\x64-mingw-qt\bin"
set "CLIENT_BUILD=%SCRIPT_DIR%\qt_client_grpcpp\build"

if not defined QT_MINGW_BIN set "QT_MINGW_BIN=C:\Qt\Tools\mingw1310_64\bin"
if not defined QT_DIR       set "QT_DIR=C:\Qt\6.11.0\mingw_64"

if not exist "%BUILD_DIR%" ( echo [deploy] ERROR: %BUILD_DIR% not found - run build_qt_vcpkg.bat. & exit /b 1 )
if not exist "%VCPKG_BIN%" ( echo [deploy] ERROR: %VCPKG_BIN% not found. & exit /b 1 )
if not exist "%QT_MINGW_BIN%\g++.exe" ( echo [deploy] ERROR: Qt MinGW not at %QT_MINGW_BIN%. & exit /b 1 )

if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%"

echo [deploy] Copying server executables from %BUILD_DIR%
for %%F in ("%BUILD_DIR%\*.exe") do (
    copy /y "%%F" "%DIST%\" >nul
    echo   - %%~nxF
)

set "HAVE_CLIENT=0"
if exist "%CLIENT_BUILD%" (
    for %%F in ("%CLIENT_BUILD%\*.exe") do (
        if not "!HAVE_CLIENT!"=="1" echo [deploy] Copying Qt client from %CLIENT_BUILD%
        copy /y "%%F" "%DIST%\" >nul
        echo   - %%~nxF
        set "HAVE_CLIENT=1"
    )
)
if "!HAVE_CLIENT!"=="0" echo [deploy] No Qt client built - server-only deploy.

echo [deploy] Copying vcpkg runtime DLLs from %VCPKG_BIN%
for %%F in (libabseil_dll.dll libcares.dll libcrypto-3-x64.dll libprotobuf.dll libprotobuf-lite.dll libre2.dll libssl-3-x64.dll libzlib1.dll legacy.dll libcurl.dll) do (
    if exist "%VCPKG_BIN%\%%F" copy /y "%VCPKG_BIN%\%%F" "%DIST%\" >nul && echo   - %%F
)
REM Pull in any other DLLs vcpkg dropped (transitive deps).  Avoid `(extra)`
REM literal parens - they conflict with for-body block delimiters in cmd.
for %%F in ("%VCPKG_BIN%\*.dll") do (
    if not exist "%DIST%\%%~nxF" (
        copy /y "%%F" "%DIST%\" >nul
        echo   - %%~nxF [extra]
    )
)

echo [deploy] Copying MinGW runtime DLLs from %QT_MINGW_BIN%
for %%F in (libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll) do (
    if exist "%QT_MINGW_BIN%\%%F" copy /y "%QT_MINGW_BIN%\%%F" "%DIST%\" >nul && echo   - %%F
)

set "WINDEPLOYQT="
for %%E in (windeployqt-qt6.exe windeployqt6.exe windeployqt.exe) do (
    if not defined WINDEPLOYQT if exist "%QT_DIR%\bin\%%E" set "WINDEPLOYQT=%QT_DIR%\bin\%%E"
)
if "!HAVE_CLIENT!"=="1" if defined WINDEPLOYQT (
    echo [deploy] Running !WINDEPLOYQT! for Qt client
    for %%F in ("%CLIENT_BUILD%\*.exe") do (
        "!WINDEPLOYQT!" --no-translations ^
            --no-system-d3d-compiler --no-opengl-sw ^
            "%DIST%\%%~nxF"
    )
)

REM run_<svc>.bat launchers - one-line, %~dp0 resolves at launch time so
REM Windows DLL search starts in dist\ where all our deps live.  Avoid
REM %% / %DIST% / %PATH% reuse (parent script has them set, would expand).
echo [deploy] Emitting run_*.bat launchers
for %%F in ("%DIST%\*.exe") do (
    call :emit_launcher "%DIST%\run_%%~nF.bat" "%%~nxF"
)

REM Re-point Nomad HCL files (deploy/*.nomad.hcl) into dist-qt-vcpkg/.
if exist "%SCRIPT_DIR%\deploy\*.nomad.hcl" (
    REM Step 1: ensure source HCLs have the project's actual path baked in.
    REM prep_nomad_paths.bat rewrites C:/path/to/<project> placeholders to
    REM the real %SCRIPT_DIR% (idempotent -- skips files already rewritten).
    if exist "%SCRIPT_DIR%\prep_nomad_paths.bat" (
        echo [deploy] Resolving Nomad HCL placeholders ^(prep_nomad_paths.bat^)
        call "%SCRIPT_DIR%\prep_nomad_paths.bat" >nul
    )
    echo [deploy] Re-pointing Nomad HCL files to %DIST%
    if not exist "%DIST%\deploy" mkdir "%DIST%\deploy"
    set "DIST_FWD=%DIST:\=/%"
    for %%H in ("%SCRIPT_DIR%\deploy\*.nomad.hcl") do call :rewrite_hcl "%%H"
)

echo.
echo [deploy] Bundle ready at %DIST%
echo [deploy] Run a service:  %DIST%\run_^<service^>.bat
echo [deploy] Or via Nomad:    nomad job run %DIST%\deploy\^<service^>.nomad.hcl
goto :eof

:emit_launcher
> "%~1" echo @echo off
>> "%~1" echo "%%~dp0%~2" %%*
exit /b 0

:rewrite_hcl
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = Get-Content -Raw -LiteralPath '%~1'; $c = $c -replace 'C:/path/to/[^/]+/dist-msys2', '%DIST_FWD%'; $c = $c -replace 'dist-msys2', 'dist-qt-vcpkg'; Set-Content -LiteralPath '%DIST%\deploy\%~nx1' -NoNewline -Value $c"
echo   - deploy\%~nx1
goto :eof
