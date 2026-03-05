; installer.nsh — Custom NSIS hooks for DevAtServGUI installer.
;
; Checks for Erlang/OTP and RabbitMQ Server during install.
; If missing, offers to install them:
;   1. Bundled: uses installers from build/installers/ (offline/enterprise)
;   2. Download: fetches from GitHub releases (lightweight distribution)
;
; Also provides a wizard page for installing the MicroserviceBase and
; ProcessHub Python libraries via pip and saving the Python path to settings.json.
;
; To bundle installers for offline install, place them in build/installers/:
;   build/installers/otp_win64_<ver>.exe
;   build/installers/rabbitmq-server-<ver>.exe
;   build/installers/microservicebase-<ver>-py3-none-any.whl
;   build/installers/processhub-<ver>-py3-none-any.whl
;
; Versions — update these when upgrading:
!define ERLANG_VER  "26.2.5"
!define RABBITMQ_VER "4.0.5"
!define MSB_VER     "2.0.0"
!define PHB_VER     "1.1.0"
!define ERLANG_INSTALLER  "otp_win64_${ERLANG_VER}.exe"
!define RABBITMQ_INSTALLER "rabbitmq-server-${RABBITMQ_VER}.exe"
!define MSB_WHEEL   "microservicebase-${MSB_VER}-py3-none-any.whl"
!define PHB_WHEEL   "processhub-${PHB_VER}-py3-none-any.whl"
!define ERLANG_URL  "https://github.com/erlang/otp/releases/download/OTP-${ERLANG_VER}/${ERLANG_INSTALLER}"
!define RABBITMQ_URL "https://github.com/rabbitmq/rabbitmq-server/releases/download/v${RABBITMQ_VER}/${RABBITMQ_INSTALLER}"

!include "LogicLib.nsh"
!include "nsDialogs.nsh"

; ===================================================================
; Installer-only code — skipped during uninstaller build pass
; ===================================================================
!ifndef BUILD_UNINSTALLER

; Global variables for the MicroserviceBase custom page
Var /GLOBAL MSB_Dialog
Var /GLOBAL MSB_CheckBox
Var /GLOBAL MSB_PythonText
Var /GLOBAL MSB_BrowseBtn
Var /GLOBAL MSB_StatusLabel
Var /GLOBAL MSB_DoInstall
Var /GLOBAL MSB_PythonPath

; Sets $R0 = "1" if Erlang is found, "0" otherwise.
Function DetectErlang
  StrCpy $R0 "0"

  ; Check 64-bit registry
  SetRegView 64
  ClearErrors
  ReadRegStr $R1 HKLM "SOFTWARE\Ericsson\Erlang" ""
  ${IfNot} ${Errors}
    StrCpy $R0 "1"
    SetRegView lastused
    Return
  ${EndIf}

  ; Check ERLANG_HOME environment variable
  ReadEnvStr $R1 "ERLANG_HOME"
  ${If} $R1 != ""
    IfFileExists "$R1\bin\erl.exe" 0 +3
      StrCpy $R0 "1"
      SetRegView lastused
      Return
  ${EndIf}

  SetRegView lastused
FunctionEnd

; Sets $R0 = "1" if RabbitMQ is found, "0" otherwise.
Function DetectRabbitMQ
  StrCpy $R0 "0"

  ; Check Windows service (most reliable — works even without registry keys)
  nsExec::ExecToStack 'sc query RabbitMQ'
  Pop $R1
  ${If} $R1 == "0"
    StrCpy $R0 "1"
    Return
  ${EndIf}

  ; Check 64-bit uninstall registry
  SetRegView 64
  ClearErrors
  ReadRegStr $R1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\RabbitMQ" "UninstallString"
  ${IfNot} ${Errors}
  ${AndIf} $R1 != ""
    StrCpy $R0 "1"
    SetRegView lastused
    Return
  ${EndIf}

  ; Check default install location
  IfFileExists "$PROGRAMFILES\RabbitMQ Server\rabbitmq_server-*\sbin\rabbitmq-server.bat" 0 +3
    StrCpy $R0 "1"
    SetRegView lastused
    Return

  ; Check rabbitmqctl in PATH
  nsExec::ExecToStack 'where rabbitmqctl'
  Pop $R1
  ${If} $R1 == "0"
    StrCpy $R0 "1"
  ${EndIf}

  SetRegView lastused
FunctionEnd

; ===================================================================
; Download helper
; Uses PowerShell (available on all modern Windows).
; $R5 = URL, $R6 = output file path.
; Sets $R0 = "0" on success.
; ===================================================================
Function DownloadFile
  DetailPrint "Downloading: $R5"
  DetailPrint "  → $R6"
  nsExec::ExecToStack 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "\
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; \
    try { \
      Invoke-WebRequest -Uri ''$R5'' -OutFile ''$R6'' -UseBasicParsing; \
      exit 0 \
    } catch { \
      Write-Error $$_.Exception.Message; \
      exit 1 \
    }"'
  Pop $R0  ; exit code
  Pop $R1  ; stdout/stderr (unused)
FunctionEnd

; ===================================================================
; Install Erlang/OTP
; Tries bundled installer first, then downloads.
; ===================================================================
Function InstallErlang
  ; Try bundled installer
  StrCpy $R2 "$INSTDIR\resources\installers\${ERLANG_INSTALLER}"
  IfFileExists $R2 erlang_run_installer

  ; Try build resources path (available during NSIS compile)
  StrCpy $R2 "$TEMP\${ERLANG_INSTALLER}"
  StrCpy $R5 "${ERLANG_URL}"
  StrCpy $R6 $R2
  Call DownloadFile
  ${If} $R0 != "0"
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Failed to download Erlang/OTP.$\n$\n\
      Please install manually from:$\n\
      https://www.erlang.org/downloads"
    Return
  ${EndIf}

  erlang_run_installer:
  DetailPrint "Installing Erlang/OTP ${ERLANG_VER}..."
  nsExec::ExecToLog '"$R2" /S'
  Pop $R0
  ${If} $R0 != "0"
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Erlang/OTP installation returned error code $R0.$\n\
      You may need to install it manually."
  ${Else}
    DetailPrint "Erlang/OTP installed successfully."
  ${EndIf}

  ; Clean up downloaded file
  Delete "$TEMP\${ERLANG_INSTALLER}"
FunctionEnd

; ===================================================================
; Install RabbitMQ Server
; Tries bundled installer first, then downloads.
; ===================================================================
Function InstallRabbitMQ
  ; Try bundled installer
  StrCpy $R2 "$INSTDIR\resources\installers\${RABBITMQ_INSTALLER}"
  IfFileExists $R2 rabbitmq_run_installer

  ; Download
  StrCpy $R2 "$TEMP\${RABBITMQ_INSTALLER}"
  StrCpy $R5 "${RABBITMQ_URL}"
  StrCpy $R6 $R2
  Call DownloadFile
  ${If} $R0 != "0"
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Failed to download RabbitMQ Server.$\n$\n\
      Please install manually from:$\n\
      https://www.rabbitmq.com/install-windows.html"
    Return
  ${EndIf}

  rabbitmq_run_installer:
  DetailPrint "Installing RabbitMQ Server ${RABBITMQ_VER}..."
  nsExec::ExecToLog '"$R2" /S'
  Pop $R0
  ${If} $R0 != "0"
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "RabbitMQ installation returned error code $R0.$\n\
      You may need to install it manually."
  ${Else}
    DetailPrint "RabbitMQ Server installed successfully."

    ; Enable and start the RabbitMQ service
    DetailPrint "Starting RabbitMQ service..."
    nsExec::ExecToLog 'sc config RabbitMQ start= auto'
    nsExec::ExecToLog 'net start RabbitMQ'
    Pop $R0
  ${EndIf}

  ; Clean up downloaded file
  Delete "$TEMP\${RABBITMQ_INSTALLER}"
FunctionEnd

; ===================================================================
; Install MicroserviceBase Python library via pip
; Tries bundled wheel first, then falls back to PyPI.
; Uses $MSB_PythonPath as the Python executable.
; ===================================================================
Function InstallMicroserviceBase
  DetailPrint "Installing MicroserviceBase Python library..."

  ; Try bundled wheel
  StrCpy $R2 "$INSTDIR\resources\installers\${MSB_WHEEL}"
  IfFileExists $R2 msb_install_wheel

  ; No bundled wheel — install from PyPI
  DetailPrint "No bundled wheel found — installing from PyPI..."
  Goto msb_install_pypi

  msb_install_wheel:
  DetailPrint "Found bundled wheel: $R2"
  nsExec::ExecToStack '"$MSB_PythonPath" -m pip install "$R2[rabbitmq,web]"'
  Pop $R0
  Pop $R1
  ${If} $R0 == "0"
    DetailPrint "MicroserviceBase installed successfully from bundled wheel."
    Return
  ${EndIf}
  DetailPrint "Bundled wheel install failed (exit code $R0) — falling back to PyPI..."

  msb_install_pypi:
  nsExec::ExecToStack '"$MSB_PythonPath" -m pip install "MicroserviceBase[rabbitmq,web]"'
  Pop $R0
  Pop $R1
  ${If} $R0 == "0"
    DetailPrint "MicroserviceBase installed successfully from PyPI."
  ${Else}
    DetailPrint "MicroserviceBase pip install failed (exit code $R0)."
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Failed to install MicroserviceBase Python library.$\n$\n\
      Please install manually by running:$\n\
      $MSB_PythonPath -m pip install $\"MicroserviceBase[rabbitmq,web]$\""
  ${EndIf}
FunctionEnd

; ===================================================================
; Install ProcessHub Python library via pip
; Tries bundled wheel first, then falls back to PyPI.
; Uses $MSB_PythonPath as the Python executable.
; ===================================================================
Function InstallProcessHub
  DetailPrint "Installing ProcessHub Python library..."

  ; Try bundled wheel
  StrCpy $R2 "$INSTDIR\resources\installers\${PHB_WHEEL}"
  IfFileExists $R2 phb_install_wheel

  ; No bundled wheel — install from PyPI
  DetailPrint "No bundled wheel found — installing from PyPI..."
  Goto phb_install_pypi

  phb_install_wheel:
  DetailPrint "Found bundled wheel: $R2"
  nsExec::ExecToStack '"$MSB_PythonPath" -m pip install "$R2"'
  Pop $R0
  Pop $R1
  ${If} $R0 == "0"
    DetailPrint "ProcessHub installed successfully from bundled wheel."
    Return
  ${EndIf}
  DetailPrint "Bundled wheel install failed (exit code $R0) — falling back to PyPI..."

  phb_install_pypi:
  nsExec::ExecToStack '"$MSB_PythonPath" -m pip install "ProcessHub"'
  Pop $R0
  Pop $R1
  ${If} $R0 == "0"
    DetailPrint "ProcessHub installed successfully from PyPI."
  ${Else}
    DetailPrint "ProcessHub pip install failed (exit code $R0)."
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Failed to install ProcessHub Python library.$\n$\n\
      Please install manually by running:$\n\
      $MSB_PythonPath -m pip install ProcessHub"
  ${EndIf}
FunctionEnd

; ===================================================================
; Save the chosen Python path into settings.json
; Uses PowerShell ConvertFrom-Json / ConvertTo-Json for safe JSON editing.
; ===================================================================
Function SavePythonPathToSettings
  StrCpy $R2 "$INSTDIR\resources\settings.json"
  IfFileExists $R2 0 msb_no_settings
  DetailPrint "Saving Python path to settings.json..."

  ; Escape backslashes for PowerShell string
  StrCpy $R3 $MSB_PythonPath
  nsExec::ExecToStack 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "\
    $$f = ''$R2''; \
    $$j = Get-Content $$f -Raw | ConvertFrom-Json; \
    $$j | Add-Member -NotePropertyName ''pythonPath'' -NotePropertyValue ''$R3'' -Force; \
    $$j | ConvertTo-Json -Depth 10 | Set-Content $$f -Encoding UTF8; \
    exit 0"'
  Pop $R0
  Pop $R1
  ${If} $R0 == "0"
    DetailPrint "Python path saved to settings.json."
  ${Else}
    DetailPrint "Warning: could not update settings.json (exit code $R0)."
  ${EndIf}
  Return

  msb_no_settings:
  DetailPrint "settings.json not found — skipping Python path save."
FunctionEnd

; Win32 combo-box message not defined by nsDialogs
!ifndef CB_FINDSTRINGEXACT
!define CB_FINDSTRINGEXACT 0x0158
!endif

; ===================================================================
; MicroserviceBase custom page — detect existing installation
; Reads the current combo text, runs pip detection, updates status.
; ===================================================================
Function MSB_DetectExisting
  ${NSD_GetText} $MSB_PythonText $MSB_PythonPath

  ${If} $MSB_PythonPath == ""
    ${NSD_SetText} $MSB_StatusLabel "No Python interpreter selected"
    Return
  ${EndIf}

  ; Only run detection if the file actually exists
  IfFileExists $MSB_PythonPath 0 msb_detect_nofile

    ; Detect MicroserviceBase
    nsExec::ExecToStack `"$MSB_PythonPath" -c "from importlib.metadata import version; print(version('MicroserviceBase'))"`
    Pop $R0
    Pop $R1
    ; Trim trailing \r\n
    ${Do}
      StrLen $R2 $R1
      ${If} $R2 == 0
        ${ExitDo}
      ${EndIf}
      IntOp $R2 $R2 - 1
      StrCpy $R3 $R1 1 $R2
      ${If} $R3 == "$\r"
      ${OrIf} $R3 == "$\n"
      ${OrIf} $R3 == " "
        StrCpy $R1 $R1 $R2
      ${Else}
        ${ExitDo}
      ${EndIf}
    ${Loop}

    ; Detect ProcessHub
    nsExec::ExecToStack `"$MSB_PythonPath" -c "from importlib.metadata import version; print(version('ProcessHub'))"`
    Pop $R4
    Pop $R5
    ; Trim trailing \r\n
    ${Do}
      StrLen $R2 $R5
      ${If} $R2 == 0
        ${ExitDo}
      ${EndIf}
      IntOp $R2 $R2 - 1
      StrCpy $R3 $R5 1 $R2
      ${If} $R3 == "$\r"
      ${OrIf} $R3 == "$\n"
      ${OrIf} $R3 == " "
        StrCpy $R5 $R5 $R2
      ${Else}
        ${ExitDo}
      ${EndIf}
    ${Loop}

    ; Build status text
    StrCpy $R6 ""
    ${If} $R0 == "0"
    ${AndIf} $R1 != ""
      StrCpy $R6 "MSB $R1"
    ${EndIf}
    ${If} $R4 == "0"
    ${AndIf} $R5 != ""
      ${If} $R6 != ""
        StrCpy $R6 "$R6, PHB $R5"
      ${Else}
        StrCpy $R6 "PHB $R5"
      ${EndIf}
    ${EndIf}

    ${If} $R6 != ""
      ${NSD_SetText} $MSB_StatusLabel "Detected: $R6 (will upgrade/reinstall)"
    ${Else}
      ${NSD_SetText} $MSB_StatusLabel "Libraries not found — will be installed fresh"
    ${EndIf}
    Return

  msb_detect_nofile:
  ${NSD_SetText} $MSB_StatusLabel "Python executable not found at this path"
FunctionEnd

; ===================================================================
; MicroserviceBase custom page — populate combo with detected Pythons.
; Adds RobotFramework path first, then each 'where python' result.
; Skips duplicates via CB_FINDSTRINGEXACT.
; ===================================================================
Function MSB_PopulateCombo
  ; 1. Add RobotFramework standard path if it exists (64-bit Program Files)
  IfFileExists "$PROGRAMFILES64\RobotFramework\python3\python.exe" 0 msb_pop_rf32
    ${NSD_CB_AddString} $MSB_PythonText "$PROGRAMFILES64\RobotFramework\python3\python.exe"
    Goto msb_pop_where
  msb_pop_rf32:
  IfFileExists "$PROGRAMFILES\RobotFramework\python3\python.exe" 0 msb_pop_where
    ${NSD_CB_AddString} $MSB_PythonText "$PROGRAMFILES\RobotFramework\python3\python.exe"
  msb_pop_where:

  ; 2. Run 'where python' and add each result
  nsExec::ExecToStack 'where python'
  Pop $R0
  Pop $R1
  ${If} $R0 != "0"
    Return
  ${EndIf}

  StrLen $R2 $R1     ; total length
  StrCpy $R3 0       ; line-start offset
  StrCpy $R4 0       ; scan offset

  ${Do}
    ${If} $R4 >= $R2
      ${ExitDo}
    ${EndIf}
    StrCpy $R5 $R1 1 $R4                   ; current char
    ${If} $R5 == "$\n"
    ${OrIf} $R5 == "$\r"
      ; --- end-of-line: extract path and add if valid & unique ---
      IntOp $R6 $R4 - $R3                  ; line length
      ${If} $R6 > 0
        StrCpy $R5 $R1 $R6 $R3             ; extracted path
        IfFileExists $R5 0 msb_pop_skip
          ; Check for duplicate
          SendMessage $MSB_PythonText ${CB_FINDSTRINGEXACT} -1 "STR:$R5" $R7
          ${If} $R7 == -1
            ${NSD_CB_AddString} $MSB_PythonText $R5
          ${EndIf}
        msb_pop_skip:
      ${EndIf}
      IntOp $R4 $R4 + 1
      StrCpy $R3 $R4                       ; advance line-start
    ${Else}
      IntOp $R4 $R4 + 1
    ${EndIf}
  ${Loop}

  ; Flush last line (if no trailing newline)
  IntOp $R6 $R4 - $R3
  ${If} $R6 > 0
    StrCpy $R5 $R1 $R6 $R3
    IfFileExists $R5 0 msb_pop_done
      SendMessage $MSB_PythonText ${CB_FINDSTRINGEXACT} -1 "STR:$R5" $R7
      ${If} $R7 == -1
        ${NSD_CB_AddString} $MSB_PythonText $R5
      ${EndIf}
  ${EndIf}
  msb_pop_done:
FunctionEnd

; ===================================================================
; MicroserviceBase custom page — timer callback
; Polls the combo text every 500 ms; re-runs detection on change.
; (nsDialogs::OnChange only catches CBN_EDITCHANGE, not CBN_SELCHANGE,
;  so a timer is the reliable way to detect dropdown selections.)
; ===================================================================
Function MSB_TimerCheck
  ${NSD_KillTimer} MSB_TimerCheck
  ${NSD_GetText} $MSB_PythonText $R8
  ${If} $R8 != $MSB_PythonPath
    Call MSB_DetectExisting        ; updates $MSB_PythonPath
  ${EndIf}
  ${NSD_CreateTimer} MSB_TimerCheck 500
FunctionEnd

; ===================================================================
; MicroserviceBase custom page — checkbox state change
; Enables/disables the path controls based on checkbox state.
; ===================================================================
Function MSB_OnCheckChange
  ${NSD_GetState} $MSB_CheckBox $R0
  ${If} $R0 == ${BST_CHECKED}
    StrCpy $MSB_DoInstall "1"
    EnableWindow $MSB_PythonText 1
    EnableWindow $MSB_BrowseBtn 1
    EnableWindow $MSB_StatusLabel 1
  ${Else}
    StrCpy $MSB_DoInstall "0"
    EnableWindow $MSB_PythonText 0
    EnableWindow $MSB_BrowseBtn 0
    EnableWindow $MSB_StatusLabel 0
  ${EndIf}
FunctionEnd

; ===================================================================
; MicroserviceBase custom page — Browse button handler
; Opens a file picker, adds the path to the combo if new, selects it.
; Detection is triggered automatically by the OnChange handler.
; ===================================================================
Function MSB_OnBrowse
  nsDialogs::SelectFileDialog open "" "Python executable (python.exe)|python.exe|All files (*.*)|*.*"
  Pop $R0
  ${If} $R0 != ""
    ; Add to combo if not already present
    SendMessage $MSB_PythonText ${CB_FINDSTRINGEXACT} -1 "STR:$R0" $R7
    ${If} $R7 == -1
      ${NSD_CB_AddString} $MSB_PythonText $R0
    ${EndIf}
    ; Select the path (triggers OnChange → detection)
    ${NSD_CB_SelectString} $MSB_PythonText $R0
    ; Also run detection explicitly in case OnChange doesn't fire
    StrCpy $MSB_PythonPath $R0
    Call MSB_DetectExisting
  ${EndIf}
FunctionEnd

; ===================================================================
; MicroserviceBase custom page — Page Create callback
; ===================================================================
Function MSB_PageCreate
  nsDialogs::Create 1018
  Pop $MSB_Dialog
  ${If} $MSB_Dialog == error
    Abort
  ${EndIf}

  ; Checkbox — "Install Python libraries (MicroserviceBase + ProcessHub)"
  ${NSD_CreateCheckBox} 0 0u 100% 12u "Install Python libraries (MicroserviceBase + ProcessHub)"
  Pop $MSB_CheckBox
  ${If} $MSB_DoInstall == "1"
    ${NSD_Check} $MSB_CheckBox
  ${EndIf}
  ${NSD_OnClick} $MSB_CheckBox MSB_OnCheckChange

  ; Label — "Python executable:"
  ${NSD_CreateLabel} 0 22u 80u 12u "Python executable:"
  Pop $R0

  ; Combo box — dropdown with detected Python paths
  ${NSD_CreateComboBox} 82u 20u 178u 100u ""
  Pop $MSB_PythonText

  ; Browse button
  ${NSD_CreateButton} 264u 19u 36u 15u "..."
  Pop $MSB_BrowseBtn
  ${NSD_OnClick} $MSB_BrowseBtn MSB_OnBrowse

  ; Status label — detection result (20u height for possible two-line text)
  ${NSD_CreateLabel} 0 40u 100% 20u ""
  Pop $MSB_StatusLabel

  ; Populate combo with detected Python interpreters
  Call MSB_PopulateCombo

  ; Pre-select the default path from customInit
  ${If} $MSB_PythonPath != ""
    ${NSD_CB_SelectString} $MSB_PythonText $MSB_PythonPath
  ${EndIf}

  ; Initial detection
  Call MSB_DetectExisting

  ; Start timer to detect combo selection / text changes (500 ms poll)
  ${NSD_CreateTimer} MSB_TimerCheck 500

  ; Apply initial enable/disable state
  Call MSB_OnCheckChange

  nsDialogs::Show
FunctionEnd

; ===================================================================
; MicroserviceBase custom page — Page Leave callback
; Validates that python.exe exists at the given path if install is checked.
; ===================================================================
Function MSB_PageLeave
  ${NSD_KillTimer} MSB_TimerCheck
  ${NSD_GetText} $MSB_PythonText $MSB_PythonPath
  ${If} $MSB_DoInstall == "1"
    IfFileExists $MSB_PythonPath msb_path_ok
      MessageBox MB_OK|MB_ICONEXCLAMATION \
        "The Python executable was not found at:$\n$MSB_PythonPath$\n$\n\
        Please select a valid python.exe or uncheck the install option."
      Abort  ; Stay on the page
    msb_path_ok:
  ${EndIf}
FunctionEnd

!endif ; !BUILD_UNINSTALLER

; ===================================================================
; customHeader — declare variables (already done at top level)
; ===================================================================
!macro customHeader
  ; Variables declared at file scope above (Var /GLOBAL ...)
!macroend

; ===================================================================
; customInit — pre-populate Python path with auto-detected default
; ===================================================================
!macro customInit
  StrCpy $MSB_DoInstall "1"
  StrCpy $MSB_PythonPath ""

  ; Pre-select project standard location if it exists (64-bit Program Files)
  IfFileExists "$PROGRAMFILES64\RobotFramework\python3\python.exe" 0 msb_init_try32
    StrCpy $MSB_PythonPath "$PROGRAMFILES64\RobotFramework\python3\python.exe"
    Goto msb_init_done
  msb_init_try32:
  IfFileExists "$PROGRAMFILES\RobotFramework\python3\python.exe" 0 msb_init_done
    StrCpy $MSB_PythonPath "$PROGRAMFILES\RobotFramework\python3\python.exe"
  msb_init_done:
!macroend

; ===================================================================
; customPageAfterChangeDir — register the MicroserviceBase page
; ===================================================================
!macro customPageAfterChangeDir
  Page custom MSB_PageCreate MSB_PageLeave
!macroend

; ===================================================================
; customInstall — runs after app files are installed
; ===================================================================
!macro customInstall
  ; --- Erlang/OTP ---
  Call DetectErlang
  ${If} $R0 == "0"
    MessageBox MB_YESNO|MB_ICONQUESTION \
      "Erlang/OTP is required by RabbitMQ but was not detected.$\n$\n\
      Install Erlang/OTP ${ERLANG_VER} now?" \
      IDYES +2
    Goto skip_erlang
    Call InstallErlang
    skip_erlang:
  ${Else}
    DetailPrint "Erlang/OTP detected — skipping."
  ${EndIf}

  ; --- RabbitMQ ---
  Call DetectRabbitMQ
  ${If} $R0 == "0"
    MessageBox MB_YESNO|MB_ICONQUESTION \
      "RabbitMQ Server is required but was not detected.$\n$\n\
      Install RabbitMQ ${RABBITMQ_VER} now?" \
      IDYES +2
    Goto skip_rabbitmq
    Call InstallRabbitMQ
    skip_rabbitmq:
  ${Else}
    DetailPrint "RabbitMQ Server detected — skipping."
  ${EndIf}

  ; --- Python libraries (MicroserviceBase + ProcessHub) ---
  ${If} $MSB_DoInstall == "1"
    Call InstallMicroserviceBase
    Call InstallProcessHub
  ${EndIf}
  ${If} $MSB_PythonPath != ""
    Call SavePythonPathToSettings
  ${EndIf}
!macroend
