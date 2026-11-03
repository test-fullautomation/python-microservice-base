@echo off
REM Extract a vcpkg_installed_x64-mingw-qt.zip into every build dir of
REM this project (server build-qt-vcpkg/, qt_client_grpcpp/build/, and
REM Qt Creator's build/Desktop_Qt_*/).  Use after a teammate has shared
REM the zip via export_prebuilt.bat - skips the 30-60 min vcpkg compile.
REM
REM Usage:
REM   import_prebuilt.bat <local-path-to-zip>
REM   import_prebuilt.bat <http(s)-url>          (downloads to %TEMP% first)
REM   import_prebuilt.bat                        (prompts interactively)
REM
REM Proxy:
REM   If you're behind a corporate proxy, set HTTPS_PROXY before running:
REM     set HTTPS_PROXY=http://127.0.0.1:3128       (e.g. cntlm)
REM     set HTTP_PROXY=http://127.0.0.1:3128
REM   Both curl and the PowerShell fallback honor HTTPS_PROXY.  Persist with
REM   setx (new shell required) or `set` per-session.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

if "%~1"=="" (
    set /p "ZIP_ARG=Enter path or URL to vcpkg_installed_x64-mingw-qt.zip: "
) else (
    REM Use %* (full command line) instead of %~1 because CMD treats =
    REM as a token separator: an unquoted https://x?e=token URL gets
    REM split into %1=https://x?e and %2=token, dropping the auth part.
    set "ZIP_ARG=%*"
)
set "ZIP_ARG=!ZIP_ARG:"=!"
if "!ZIP_ARG!"=="" ( echo [import] ERROR: no zip path/URL. & exit /b 1 )

REM URL or local path?  If http(s), download to %TEMP% first via curl.exe.
set "IS_URL=0"
if /i "!ZIP_ARG:~0,7!"=="http://"  set "IS_URL=1"
if /i "!ZIP_ARG:~0,8!"=="https://" set "IS_URL=1"

set "CURL_EXE=%SystemRoot%\System32\curl.exe"
set "TAR_EXE=%SystemRoot%\System32\tar.exe"
if not exist "%TAR_EXE%" ( echo [import] ERROR: %TAR_EXE% missing.  Need Win10 1803+. & exit /b 1 )

if "!IS_URL!"=="0" goto :_use_local

if not exist "%CURL_EXE%" ( echo [import] ERROR: %CURL_EXE% missing.  Need Win10 1803+. & exit /b 1 )

REM SharePoint host?  Used to decide whether to (a) auto-append download=1
REM and (b) retry with PowerShell + Windows credentials when curl fails.
set "IS_SHAREPOINT=0"
echo !ZIP_ARG! | findstr /i "sharepoint.com" >nul && set "IS_SHAREPOINT=1"

REM SharePoint share links (/:u:/p/... or /:u:/r/...) serve an HTML
REM viewer page by default.  Append download=1 to force file bytes.
set "DL_URL=!ZIP_ARG!"
if "!IS_SHAREPOINT!"=="1" (
    echo !DL_URL! | findstr /i "download=1" >nul
    if errorlevel 1 (
        REM has query string already?  use & else ?
        echo !DL_URL! | findstr "?" >nul
        if errorlevel 1 ( set "DL_URL=!DL_URL!?download=1" ) else ( set "DL_URL=!DL_URL!&download=1" )
        echo [import] SharePoint link detected - appending download=1
    )
)

set "ZIP_PATH=%TEMP%\vcpkg_installed_x64-mingw-qt.zip"
echo [import] Downloading: !DL_URL!
echo [import] Saving to  : !ZIP_PATH!

REM Attempt 1: curl.  Honors HTTPS_PROXY/HTTP_PROXY env vars natively
REM (e.g. set HTTPS_PROXY=http://127.0.0.1:3128 for a local cntlm instance).
"%CURL_EXE%" -fL --retry 3 --retry-delay 2 -o "!ZIP_PATH!" "!DL_URL!"
if not errorlevel 1 goto :_post_download

REM Attempt 2 (SharePoint only): PowerShell with -UseDefaultCredentials,
REM which sends the current Windows session's NT/Negotiate creds for SSO.
REM -Proxy honors HTTPS_PROXY (same as curl).  -ProxyUseDefaultCredentials
REM is harmless if proxy doesn't ask for auth (e.g. cntlm relays for us).
if "!IS_SHAREPOINT!"=="1" (
    echo [import] curl failed - retrying via PowerShell with Windows credentials ^(SSO/NTLM^)...
    set "PS_PROXY="
    if not "%HTTPS_PROXY%"=="" set "PS_PROXY=-Proxy '%HTTPS_PROXY%'"
    if "!PS_PROXY!"=="" if not "%HTTP_PROXY%"=="" set "PS_PROXY=-Proxy '%HTTP_PROXY%'"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '!DL_URL!' -UseDefaultCredentials -ProxyUseDefaultCredentials !PS_PROXY! -OutFile '!ZIP_PATH!' -UseBasicParsing -ErrorAction Stop; exit 0 } catch { Write-Host ('  ' + $_.Exception.Message); exit 1 }"
    if not errorlevel 1 goto :_post_download
)

echo [import] ERROR: download failed.
echo [import]        Common causes:
echo [import]          - Tenant requires modern auth ^(no Negotiate^).  Open the
echo [import]            link in a browser, save the file, then re-run with the
echo [import]            local path: import_prebuilt.bat C:\path\to\file.zip
echo [import]          - URL is a share-page URL, not the file.  In SharePoint:
echo [import]            Share -^> Settings -^> Anyone with link, View ^(if policy allows^).
echo [import]          - Corporate proxy blocking the request.
exit /b 1

:_post_download
if not exist "!ZIP_PATH!" ( echo [import] ERROR: download produced no file. & exit /b 1 )

REM Sanity check: did we get a zip or an HTML login/error page?
"%TAR_EXE%" -tf "!ZIP_PATH!" >nul 2>&1
if errorlevel 1 (
    echo [import] ERROR: downloaded file is not a valid zip.
    REM Peek at first 200 bytes so user can diagnose - HTML pages start
    REM with "<!DOCTYPE" or "<html"; sign-in pages mention "login.microsoftonline".
    echo [import] First bytes of downloaded file:
    powershell -NoProfile -Command "Get-Content -LiteralPath '!ZIP_PATH!' -TotalCount 3 -ErrorAction SilentlyContinue | ForEach-Object { '[import]   ' + $_.Substring(0, [Math]::Min(160, $_.Length)) }"
    echo [import]
    echo [import] Most likely cause: SharePoint served a sign-in HTML page
    echo [import] because Bosch SPO requires OAuth ^(Negotiate/NTLM disabled^).
    echo [import] Curl and PowerShell -UseDefaultCredentials can't satisfy this.
    echo [import]
    echo [import] Workarounds, in order of effort:
    echo [import]   1. Download once in your browser ^(you're already signed in^),
    echo [import]      then re-run with the local path:
    echo [import]        import_prebuilt.bat C:\path\to\file.zip
    echo [import]   2. Re-share the file as "Anyone with the link" if Bosch policy
    echo [import]      permits ^(OneDrive: Share -^> Settings -^> Anyone^).  Then this
    echo [import]      script's curl path works without auth.
    echo [import]   3. Host the zip on a fileshare/internal HTTP that doesn't
    echo [import]      require OAuth.
    exit /b 1
)
goto :_have_zip

:_use_local
set "ZIP_PATH=!ZIP_ARG!"
if not exist "!ZIP_PATH!" ( echo [import] ERROR: not found: !ZIP_PATH! & exit /b 1 )

:_have_zip

echo [import] Source zip : !ZIP_PATH!
echo [import] Project    : %SCRIPT_DIR%
set /a "EXTRACTED_COUNT=0"
set "EXTRACTED_TARGETS="
set "WARN_HOST_TOOLS_MISSING=0"

if exist "%SCRIPT_DIR%\build_qt_vcpkg.bat" (
    call :extract_to "%SCRIPT_DIR%\build-qt-vcpkg" "server"
)
for /d %%D in ("%SCRIPT_DIR%\build\Desktop_Qt_*") do (
    call :extract_to "%%D" "qt-creator-server[%%~nxD]"
)
if exist "%SCRIPT_DIR%\qt_client_grpcpp\build_qt.bat" (
    call :extract_to "%SCRIPT_DIR%\qt_client_grpcpp\build" "qt-grpcpp-client"
)
REM client/ + qt_client_grpcpp/ when opened standalone in Qt Creator
REM (each gets its own build/Desktop_Qt_*/ subdir).
for /d %%D in ("%SCRIPT_DIR%\client\build\Desktop_Qt_*") do (
    call :extract_to "%%D" "qt-creator-client[%%~nxD]"
)
for /d %%D in ("%SCRIPT_DIR%\qt_client_grpcpp\build\Desktop_Qt_*") do (
    call :extract_to "%%D" "qt-creator-grpcpp[%%~nxD]"
)

if !EXTRACTED_COUNT!==0 (
    echo.
    echo [import] WARN: no build_qt_vcpkg.bat / qt_client_grpcpp\build_qt.bat /
    echo [import]       build\Desktop_Qt_* found.  Run from project root.
    exit /b 1
)

echo;
echo [import] Done.  Extracted to !EXTRACTED_COUNT! target(s):!EXTRACTED_TARGETS!
if "!WARN_HOST_TOOLS_MISSING!"=="1" (
    echo;
    echo [import] WARN: host tools missing in zip - x64-windows\tools\grpc\grpc_cpp_plugin.exe.
    echo [import]       Cross-triplet codegen will fail at CMake configure.
    echo [import]       Fix: re-export from a build dir with host tools, then re-import.
)
echo;
echo [import] Next steps:
if exist "%SCRIPT_DIR%\build_qt_vcpkg.bat" (
    echo   set USE_PREBUILT_VCPKG=1 ^&^& build_qt_vcpkg.bat
)
if exist "%SCRIPT_DIR%\qt_client_grpcpp\build_qt.bat" (
    echo   cd qt_client_grpcpp ^&^& set USE_PREBUILT_VCPKG=1 ^&^& build_qt.bat
)
echo   :: Qt Creator: set VCPKG_MANIFEST_INSTALL=OFF in Initial Configuration.
endlocal
goto :eof

:extract_to
set "DEST_PARENT=%~1\vcpkg_installed"
set "LABEL=%~2"
if exist "%DEST_PARENT%\x64-mingw-qt"      rmdir /s /q "%DEST_PARENT%\x64-mingw-qt"
if exist "%DEST_PARENT%\x64-windows\tools" rmdir /s /q "%DEST_PARENT%\x64-windows\tools"
if not exist "%DEST_PARENT%" mkdir "%DEST_PARENT%"
echo [import] %LABEL%: extracting -^> %DEST_PARENT%
"%TAR_EXE%" -xf "!ZIP_PATH!" -C "%DEST_PARENT%"
if errorlevel 1 ( echo [import] tar failed for %LABEL%. & exit /b 1 )
if not exist "%DEST_PARENT%\x64-mingw-qt\share\grpc" (
    echo [import] WARN: %LABEL%: x64-mingw-qt\share\grpc missing - wrong zip?
    exit /b 0
)
if not exist "%DEST_PARENT%\x64-windows\tools\grpc\grpc_cpp_plugin.exe" (
    set "WARN_HOST_TOOLS_MISSING=1"
)
set /a "EXTRACTED_COUNT+=1"
set "EXTRACTED_TARGETS=!EXTRACTED_TARGETS! !LABEL!"
goto :eof
