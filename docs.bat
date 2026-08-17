@echo off
REM ===================================================================
REM  Build / serve / verify the ProperDocs site (Windows).
REM
REM  Usage:
REM    docs                 Serve with live reload on http://127.0.0.1:8000
REM    docs serve [PORT]    Serve on a specific port
REM    docs build           One-off build into site\
REM    docs verify          Build, then decode every diagram and fail on errors
REM    docs open            Open the last built site in your browser
REM    docs clean           Delete site\ and the generated docs\gui, docs\examples
REM
REM  Override the interpreter by setting PYTHON_EXE before calling, e.g.
REM    set "PYTHON_EXE=C:\Python312\python.exe" && docs build
REM ===================================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0"

REM --- Interpreter ---------------------------------------------------
REM The bare `python` on PATH is often a WSL shim with no pip, so prefer
REM the RobotFramework interpreter that actually has properdocs.
if not defined PYTHON_EXE set "PYTHON_EXE=C:\Program Files\RobotFramework\python3\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [WARN] %PYTHON_EXE% not found - falling back to python on PATH.
    set "PYTHON_EXE=python"
)

set "CMD=%~1"
if "%CMD%"=="" set "CMD=serve"

REM --- Preflight: toolchain ------------------------------------------
"%PYTHON_EXE%" -c "import properdocs" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] properdocs is not installed for:
    echo         %PYTHON_EXE%
    echo.
    echo   Install the toolchain with:
    echo     "%PYTHON_EXE%" -m pip install properdocs properdocs-theme-readthedocs plantuml-markdown mkdocs-glightbox
    exit /b 1
)

REM --- Preflight: Java + PlantUML jar (needed to render diagrams) -----
if /i not "%CMD%"=="clean" if /i not "%CMD%"=="open" (
    where java >nul 2>&1
    if errorlevel 1 (
        echo [WARN] java not on PATH - diagrams will render as error images.
    )
    if not exist "tools\plantuml.jar" (
        echo [ERROR] tools\plantuml.jar is missing ^(it is gitignored^).
        echo.
        echo   Copy one in, e.g. from the VS Code PlantUML extension:
        echo     copy "%%USERPROFILE%%\.vscode\extensions\jebbs.plantuml-*\plantuml.jar" tools\
        echo.
        echo   Or download:
        echo     https://github.com/plantuml/plantuml/releases
        exit /b 1
    )
)

REM --- Dispatch -------------------------------------------------------
if /i "%CMD%"=="serve"  goto :serve
if /i "%CMD%"=="build"  goto :build
if /i "%CMD%"=="verify" goto :verify
if /i "%CMD%"=="open"   goto :open
if /i "%CMD%"=="clean"  goto :clean

echo Unknown command: %CMD%
echo Usage: docs [serve^|build^|verify^|open^|clean]
exit /b 2

:serve
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8000"
echo.
echo   Serving on http://127.0.0.1:%PORT%/
echo   First render takes ~45s ^(25 PlantUML diagrams^); edits reload in seconds.
echo   Press Ctrl+C to stop.
echo.
"%PYTHON_EXE%" -m properdocs serve --dev-addr 127.0.0.1:%PORT%
exit /b %errorlevel%

:build
echo Building site\ ...
"%PYTHON_EXE%" -m properdocs build --clean --strict -f properdocs.yml
if errorlevel 1 (
    echo.
    echo [FAILED] Build error ^(--strict: warnings are fatal, same as CI^).
    exit /b 1
)
echo.
echo [OK] Built to site\  -  run "docs open" to view it.
exit /b 0

:verify
echo Building site\ ...
"%PYTHON_EXE%" -m properdocs build --clean --strict -f properdocs.yml
if errorlevel 1 (
    echo [FAILED] Build error.
    exit /b 1
)
echo.
echo Verifying diagrams ^(decodes each SVG - a failed diagram renders as a
echo valid image saying "Syntax Error", so counting them is not enough^)...
"%PYTHON_EXE%" tools\verify_diagrams.py site
if errorlevel 1 (
    echo.
    echo [FAILED] One or more diagrams did not render.
    exit /b 1
)
echo.
echo [OK] Build and diagrams verified - this is what CI runs.
exit /b 0

:open
if not exist "site\index.html" (
    echo [ERROR] site\index.html not found - run "docs build" first.
    exit /b 1
)
start "" "site\index.html"
exit /b 0

:clean
if exist "site"          rmdir /s /q "site"
if exist "docs\gui"      rmdir /s /q "docs\gui"
if exist "docs\examples" rmdir /s /q "docs\examples"
echo [OK] Removed site\, docs\gui\, docs\examples\
exit /b 0
