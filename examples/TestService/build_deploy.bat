@echo off
:: Build the TestService multi-service binary.
setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
call "%SCRIPT_DIR%\set_env.bat"
cmake -S "%SCRIPT_DIR%" -B "%SCRIPT_DIR%\build" -G Ninja ^
    -DCMAKE_BUILD_TYPE=Release || exit /b 1
cmake --build "%SCRIPT_DIR%\build" --config Release || exit /b 1
echo [build] OK -^> %SCRIPT_DIR%\build\test_service.exe
endlocal
