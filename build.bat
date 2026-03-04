@echo off
REM Build DevAtServGUI installer for Windows
REM Usage: build.bat [--pack]
REM   --pack  Build unpacked directory only (faster, for testing)
REM   (default) Build NSIS installer (.exe)

cd /d "%~dp0"

REM --- Configurable Python path (edit here or set before calling) ---
if not defined PYTHON_PATH set "PYTHON_PATH=C:\Program Files\RobotFramework\python3\python.exe"

echo [1/3] Checking prerequisites...
where node >nul 2>&1 || (echo ERROR: Node.js not found in PATH && exit /b 1)
where npm >nul 2>&1 || (echo ERROR: npm not found in PATH && exit /b 1)

echo [2/3] Installing dependencies...
if not exist node_modules (
    call npm install
    if errorlevel 1 (
        echo ERROR: npm install failed
        exit /b 1
    )
)

echo [3/4] Building MicroserviceBase wheel...
if not exist "%PYTHON_PATH%" (
    echo WARNING: Python not found at %PYTHON_PATH%, skipping wheel build
    goto skip_wheel
)
set "SKIP_DOCBUILD=1"
"%PYTHON_PATH%" -m pip wheel --no-deps -w "%~dp0build-resources\installers" "%~dp0..\.."
set "SKIP_DOCBUILD="
if errorlevel 1 (
    echo WARNING: Wheel build failed, installer will fall back to PyPI
) else (
    echo Wheel built to build-resources\installers\
)
:skip_wheel

echo [4/4] Building...
if "%1"=="--pack" (
    echo Building unpacked directory...
    call npx electron-builder --dir
) else (
    echo Building NSIS installer...
    call npx electron-builder --win --x64
)

if errorlevel 1 (
    echo ERROR: Build failed
    exit /b 1
)

echo.
echo Build complete. Output in dist\
