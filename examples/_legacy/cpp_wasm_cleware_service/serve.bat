@echo off
:: Serve the Qt WASM build output with HTTP-to-RabbitMQ bridge.
::
:: Usage:
::   serve.bat              (default port 8090)
::   serve.bat 9000         (custom port)

setlocal

set PORT=%1
if "%PORT%"=="" set PORT=8090

set "PY=%RobotPythonPath%\python.exe"
if not exist "%PY%" (
    echo WARNING: RobotPythonPath not set, falling back to system python.
    set PY=python
)

start http://localhost:%PORT%/servicecleware_wasm.html

"%PY%" "%~dp0serve_dev.py" %PORT%
