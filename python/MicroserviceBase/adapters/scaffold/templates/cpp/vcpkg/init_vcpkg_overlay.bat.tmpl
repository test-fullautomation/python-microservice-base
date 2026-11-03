@echo off
REM ---------------------------------------------------------------------------
REM init_vcpkg_overlay.bat - setup for the ports/grpc/ overlay.
REM
REM We ship only the gcc 13.1.0 ICE workaround patch; the rest of the
REM grpc port files (portfile.cmake, vcpkg.json, 00001..00017 patches,
REM cmake glue) come from %VCPKG_ROOT%\ports\grpc\.  This script
REM copies them, then patches portfile.cmake (ICE patch line + force
REM gRPC_BUILD_CODEGEN=ON so grpc++_reflection ships).
REM
REM Modes:
REM   (no flag)    Initialise if missing.  No-op if already initialised.
REM   --upgrade    Re-apply all patches in-place (idempotent).  Use this
REM                after pulling a newer mb-scaffold to pick up patch
REM                changes without losing local edits to portfile.cmake.
REM   --reinit     Wipe ports/grpc/ and re-copy + re-patch from scratch.
REM                Use when upstream's vcpkg grpc port changed and you
REM                want the new upstream files.
REM ---------------------------------------------------------------------------
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "OVERLAY=%SCRIPT_DIR%\ports\grpc"

REM ---- arg parsing -------------------------------------------------------
set "MODE=init"
if /i "%~1"=="--reinit"  set "MODE=reinit"
if /i "%~1"=="--upgrade" set "MODE=upgrade"
if /i "%~1"=="-r"        set "MODE=reinit"
if /i "%~1"=="-u"        set "MODE=upgrade"
if /i "%~1"=="--help"    goto :help
if /i "%~1"=="-h"        goto :help
if /i "%~1"=="/?"        goto :help

if "%MODE%"=="reinit" (
    echo [init_vcpkg_overlay] --reinit: wiping %OVERLAY%
    rmdir /s /q "%OVERLAY%" 2>nul
    set "MODE=init"
)

if "%MODE%"=="init" (
    if exist "%OVERLAY%\portfile.cmake" (
        echo [init_vcpkg_overlay] Already initialised: %OVERLAY%\portfile.cmake
        echo   --upgrade  re-apply patches in place ^(no upstream re-copy^)
        echo   --reinit   wipe + re-copy + re-patch from VCPKG_ROOT
        exit /b 0
    )
    if not defined VCPKG_ROOT (
        echo [init_vcpkg_overlay] ERROR: VCPKG_ROOT is not set.
        echo   setx VCPKG_ROOT C:\vcpkg
        exit /b 1
    )
    if not exist "%VCPKG_ROOT%\ports\grpc\portfile.cmake" (
        echo [init_vcpkg_overlay] ERROR: %VCPKG_ROOT%\ports\grpc not found.
        exit /b 1
    )
    echo [init_vcpkg_overlay] Copying upstream grpc port from %VCPKG_ROOT%\ports\grpc
    xcopy /e /y /q "%VCPKG_ROOT%\ports\grpc\*" "%OVERLAY%\" >nul
)

if not exist "%OVERLAY%\portfile.cmake" (
    echo [init_vcpkg_overlay] ERROR: %OVERLAY%\portfile.cmake missing.
    echo   Run without --upgrade first to copy from VCPKG_ROOT.
    exit /b 1
)

REM Patch portfile.cmake.  All edits below are idempotent: the
REM PowerShell guards check whether the change is already present
REM before applying it, so --upgrade can be re-run safely after the
REM init script changes.  Edits:
REM   1. Append 00018 ICE workaround to the PATCHES list.
REM   2. Drop the `codegen` row from vcpkg_check_features so vcpkg's
REM      manifest-mode feature selection can't accidentally turn it off
REM      (it gates upstream's grpc++_reflection target on this flag).
REM   3. Force gRPC_BUILD_CODEGEN=ON via an explicit set() above
REM      vcpkg_cmake_configure and a -D in OPTIONS.  Without this,
REM      gRPC::grpc++_reflection isn't built/installed for the target
REM      triplet and the Manager GUI gets UNIMPLEMENTED on every
REM      reflection RPC.  See examples/docs/html/vcpkg_setup.html.
REM PowerShell (always at System32\WindowsPowerShell - no Python dep).
echo [init_vcpkg_overlay] Patching portfile.cmake (idempotent: ICE patch + force CODEGEN ON)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = '%OVERLAY%\portfile.cmake'; $nl = [char]10; $c = Get-Content -Raw -LiteralPath $p; if (-not $c.Contains('00018-gcc13-per-cpu-ice-workaround.patch')) { $m = '00017-add-missing-include-file.patch'; $q = $m + $nl + (' ' * 8) + '00018-gcc13-per-cpu-ice-workaround.patch'; $c = $c.Replace($m, $q) }; $c = $c.Replace('        codegen     gRPC_BUILD_CODEGEN' + $nl, ''); if (-not $c.Contains('set(gRPC_BUILD_CODEGEN ON)')) { $c = $c.Replace('vcpkg_cmake_configure(', '# MicroserviceBase override: force CODEGEN on so grpc++_reflection is built+installed.' + $nl + 'set(gRPC_BUILD_CODEGEN ON)' + $nl + $nl + 'vcpkg_cmake_configure(') }; if (-not $c.Contains('-DgRPC_BUILD_CODEGEN=ON')) { $c = $c.Replace('        -DgRPC_INSTALL=ON', '        -DgRPC_BUILD_CODEGEN=ON' + $nl + '        -DgRPC_INSTALL=ON') }; Set-Content -LiteralPath $p -NoNewline -Value $c"
if errorlevel 1 (
    echo [init_vcpkg_overlay] Failed to patch portfile.cmake.
    exit /b 1
)

echo [init_vcpkg_overlay] Done.  Overlay-port ready at %OVERLAY%
endlocal
exit /b 0

:help
echo Usage: init_vcpkg_overlay.bat [--upgrade^|--reinit]
echo.
echo   (no flag)   Initialise the overlay if missing; no-op otherwise.
echo   --upgrade   Re-apply all patches to the existing portfile.cmake.
echo               Use after pulling a newer mb-scaffold to pick up
echo               patch changes (idempotent, safe to re-run).
echo   --reinit    Wipe ports/grpc/ and re-copy + re-patch from scratch.
echo               Use when upstream's vcpkg grpc port changed and you
echo               want the new upstream files.
exit /b 0
