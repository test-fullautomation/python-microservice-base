@echo off
:: Fresh-PC bootstrap for the MicroserviceManagerGUI.
::
::   1. If system Node.js isn't on PATH, download a portable copy into
::      `tools/node/` (no admin rights needed) and use it.
::   2. Run `npm install` if `node_modules/` is missing.
::   3. Launch the Manager GUI via `npm start`.
::
:: Re-running after the first setup is a no-op for (1) and (2) — just
:: starts the GUI.  Safe to call from a desktop shortcut.

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "NODE_VERSION=20.18.0"
set "NODE_DIST=node-v%NODE_VERSION%-win-x64"
set "NODE_URL=https://nodejs.org/dist/v%NODE_VERSION%/%NODE_DIST%.zip"
set "TOOLS_DIR=%SCRIPT_DIR%tools"
set "NODE_DIR=%TOOLS_DIR%\node"

:: --------------------------------------------------------------
:: 1) Locate Node.js
:: --------------------------------------------------------------
where node >nul 2>&1
if %errorlevel%==0 (
    echo [1/3] Using system Node.js.
    goto have_node
)
if exist "%NODE_DIR%\node.exe" (
    echo [1/3] Using portable Node.js at %NODE_DIR%.
    set "PATH=%NODE_DIR%;%PATH%"
    goto have_node
)

echo [1/3] Node.js not found — downloading portable v%NODE_VERSION% ^(~30MB^)...
if not exist "%TOOLS_DIR%" mkdir "%TOOLS_DIR%"
set "NODE_ZIP=%TEMP%\ms_mgr_node.zip"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%NODE_URL%' -OutFile '%NODE_ZIP%'"
if errorlevel 1 (
    echo ERROR: Download failed.  Check your network / proxy.
    exit /b 1
)

echo     Extracting...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Expand-Archive -Path '%NODE_ZIP%' -DestinationPath '%TOOLS_DIR%' -Force"
if errorlevel 1 (
    echo ERROR: Extract failed.
    exit /b 1
)

if exist "%NODE_DIR%" rmdir /S /Q "%NODE_DIR%"
ren "%TOOLS_DIR%\%NODE_DIST%" node
del "%NODE_ZIP%" >nul 2>&1

set "PATH=%NODE_DIR%;%PATH%"
echo     Portable Node.js installed at %NODE_DIR%.

:have_node
for /f "delims=" %%V in ('node --version 2^>nul') do set "NODE_VER=%%V"
for /f "delims=" %%V in ('npm  --version 2^>nul') do set "NPM_VER=%%V"
echo     node=%NODE_VER%  npm=%NPM_VER%

:: --------------------------------------------------------------
:: 2) npm install (one-time)
:: --------------------------------------------------------------
if exist "%SCRIPT_DIR%node_modules\electron\package.json" (
    echo [2/3] node_modules already present — skipping npm install.
) else (
    echo [2/3] Installing npm dependencies ^(first run only^)...
    pushd "%SCRIPT_DIR%" >nul
    call npm install
    set "NPM_RC=!errorlevel!"
    popd >nul
    if not "!NPM_RC!"=="0" (
        echo ERROR: npm install failed ^(exit !NPM_RC!^).
        exit /b !NPM_RC!
    )
)

:: --------------------------------------------------------------
:: 3) Launch
:: --------------------------------------------------------------
echo [3/3] Starting Manager GUI...
pushd "%SCRIPT_DIR%" >nul
call npm start
set "RUN_RC=!errorlevel!"
popd >nul
endlocal & exit /b %RUN_RC%
