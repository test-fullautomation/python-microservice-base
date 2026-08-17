@echo off
REM Replace `C:/path/to/<project>` placeholder in deploy\*.nomad.hcl with
REM the actual absolute path of THIS project (forward-slash form).  Run
REM ONCE after scaffold so Nomad job specs point at the real dist dir.
REM Idempotent.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "DEPLOY_DIR=%SCRIPT_DIR%\deploy"
set "PROJECT_FWD=%SCRIPT_DIR:\=/%"

if not exist "%DEPLOY_DIR%\*.nomad.hcl" (
    echo [prep_nomad] No HCL files in %DEPLOY_DIR% - nothing to do.
    exit /b 0
)

echo [prep_nomad] Updating placeholders in %DEPLOY_DIR%\*.nomad.hcl
echo [prep_nomad] Replacing C:/path/to/^<project^> -^> %PROJECT_FWD%

for %%H in ("%DEPLOY_DIR%\*.nomad.hcl") do call :rewrite "%%H"

echo.
echo [prep_nomad] Done.  HCL files now reference: %PROJECT_FWD%/dist-msys2/run_^<svc^>.bat
echo                 (deploy_qt_vcpkg.bat will swap dist-msys2 -^> dist-qt-vcpkg
echo                  in dist-qt-vcpkg\deploy\ copies automatically.)
endlocal
goto :eof

:rewrite
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = '%~1'; $c = Get-Content -Raw -LiteralPath $p; $new = $c -replace 'C:/path/to/[^/]+', '%PROJECT_FWD%'; if ($new -ne $c) { Set-Content -LiteralPath $p -NoNewline -Value $new; Write-Host '  - %~nx1 (updated)' } else { Write-Host '  - %~nx1 (no placeholder, skipped)' }"
goto :eof
