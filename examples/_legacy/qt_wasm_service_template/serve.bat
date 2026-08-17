@echo off
:: Serve the Qt WASM build output with HTTP-to-RabbitMQ bridge.
:: The dev server injects callMicroservice() so the WASM GUI can
:: communicate with the running MyQtWasmService.exe backend.
::
:: Usage:
::   serve.bat              (default port 8090)
::   serve.bat 9000         (custom port)
::   serve.bat 9000 path    (custom port and build directory)
::
:: Prerequisites:
::   - MyQtWasmService.exe running (connected to RabbitMQ)
::   - MicroserviceBase installed in RobotPythonPath

setlocal

set PORT=%1
if "%PORT%"=="" set PORT=8090

set BUILD_DIR=%2

:: Use RobotFramework Python (has MicroserviceBase + pika)
set "PY=%RobotPythonPath%\python.exe"
if not exist "%PY%" (
    echo WARNING: RobotPythonPath not set or python not found at "%PY%"
    echo          Falling back to system python.
    set PY=python
)

:: Open browser
start http://localhost:%PORT%/myqtwasmservice.html

:: Launch dev server
if "%BUILD_DIR%"=="" (
    "%PY%" "%~dp0serve_dev.py" %PORT%
) else (
    "%PY%" "%~dp0serve_dev.py" %PORT% "%BUILD_DIR%"
)
