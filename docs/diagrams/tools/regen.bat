@echo off
rem ---------------------------------------------------------------------------
rem  Regenerate the diagrams referenced by packagedoc/additional_docs/Description.tex.
rem
rem  Requires Java 11+ on PATH (or set %JAVA_EXE% to a specific java.exe).  The
rem  PlantUML jar is fetched into this folder on first use and is gitignored.
rem
rem  Usage:  docs\diagrams\tools\regen.bat
rem ---------------------------------------------------------------------------

setlocal enabledelayedexpansion

set "TOOLS_DIR=%~dp0"
set "REPO_ROOT=%TOOLS_DIR%..\..\.."
set "SRC=%REPO_ROOT%\docs\diagrams"
set "DST=%REPO_ROOT%\packagedoc\additional_docs\pictures"
set "JAR=%TOOLS_DIR%plantuml.jar"

if not exist "%JAR%" (
  echo Downloading plantuml.jar ...
  powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/plantuml/plantuml/releases/latest/download/plantuml.jar' -OutFile '%JAR%'"
  if errorlevel 1 ( echo Failed to download plantuml.jar & exit /b 1 )
)

if not defined JAVA_EXE set "JAVA_EXE=java"

rem PNG-slot map: <puml basename> -> <target png name>
set "TMP=%DST%\_tmp"
if not exist "%TMP%" mkdir "%TMP%"

call :render component                 overview
call :render hexagonal_architecture    architecture_overview
call :render class_adapters            architecture_detail
call :render gui_architecture          gui_architecture
call :render sequence_communication    sequence_communication
call :render state_process_lifecycle   state_process_lifecycle

rmdir "%TMP%" 2>nul
echo Done.
exit /b 0

:render
"%JAVA_EXE%" -jar "%JAR%" -tpng -o "%TMP%" "%SRC%\%~1.puml" >nul
if errorlevel 1 ( echo PlantUML failed for %~1.puml & exit /b 1 )
move /Y "%TMP%\%~1.png" "%DST%\%~2.png" >nul
echo   %~1.puml  ->  %~2.png
exit /b 0
