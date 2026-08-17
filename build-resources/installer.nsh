; installer.nsh — Custom NSIS hooks for DevAtServGUI installer.
;
; Post-migration to gRPC + Consul + Nomad:
;   - The infrastructure check now covers Consul + Nomad (the new substrate).
;   - The Erlang + RabbitMQ blocks are kept in source but DEACTIVATED via
;     `!if 0 ... !endif` guards.  Re-activate by flipping the ENABLE_LEGACY_BROKER
;     flag below to 1 if you need to install services that still use the old
;     RabbitMQ transport alongside the new Consul/Nomad path.
;
; What this installer does:
;   1. Detect Consul + Nomad on the target machine.  If missing, offer:
;        - Install via winget (pinned versions below)
;        - Provide an existing path (file picker)
;        - Skip — install later
;   2. Persist the chosen Consul/Nomad executable paths to settings.json.
;   3. (Optional) Install MicroserviceBase + ProcessHub Python libraries via pip.
;   4. (Deactivated by default) Install Erlang/OTP + RabbitMQ Server for the
;      legacy broker path.
;
; To bundle installers for offline install (legacy block only — Consul/Nomad
; use winget), place them in build/installers/:
;   build/installers/otp_win64_<ver>.exe
;   build/installers/rabbitmq-server-<ver>.exe
;   build/installers/microservicebase-<ver>-py3-none-any.whl
;   build/installers/processhub-<ver>-py3-none-any.whl
;
; ---- Set to 1 to re-enable the legacy Erlang+RabbitMQ install flow ----
!define ENABLE_LEGACY_BROKER 0

; ---- Set to 1 to re-enable the legacy ProcessHub Python install flow ----
;      (Nomad replaces ProcessHub as the orchestrator post-migration.)
!define ENABLE_LEGACY_PROCESSHUB 0

; Checkbox label adapts to whether ProcessHub is in the picture.
!if ${ENABLE_LEGACY_PROCESSHUB} == 1
  !define MSB_CHECKBOX_LABEL "Install Python libraries (MicroserviceBase + ProcessHub)"
!else
  !define MSB_CHECKBOX_LABEL "Install MicroserviceBase Python library"
!endif

; Versions — must match a release that actually exists in winget.
; Verify with:  winget show Hashicorp.Consul --versions
;               winget show Hashicorp.Nomad  --versions
; Bump these to the highest tested patch of the line you want to pin.
!define CONSUL_VER  "1.20.6"
!define NOMAD_VER   "1.9.6"
!define CONSUL_WINGET_ID "Hashicorp.Consul"
!define NOMAD_WINGET_ID  "Hashicorp.Nomad"

!define ERLANG_VER  "26.2.5"
!define RABBITMQ_VER "4.0.5"
!define MSB_VER     "2.2.0"
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

; Global variables for the Infrastructure (Consul + Nomad) custom page
Var /GLOBAL INF_Dialog
; --- per-tool dialog handles (Consul) ---
Var /GLOBAL INF_ConsulStatusLabel
Var /GLOBAL INF_ConsulInstallRb
Var /GLOBAL INF_ConsulProvideRb
Var /GLOBAL INF_ConsulSkipRb
Var /GLOBAL INF_ConsulPathText
Var /GLOBAL INF_ConsulBrowseBtn
; --- per-tool dialog handles (Nomad) ---
Var /GLOBAL INF_NomadStatusLabel
Var /GLOBAL INF_NomadInstallRb
Var /GLOBAL INF_NomadProvideRb
Var /GLOBAL INF_NomadSkipRb
Var /GLOBAL INF_NomadPathText
Var /GLOBAL INF_NomadBrowseBtn
; --- chosen actions + paths (read in customInstall) ---
Var /GLOBAL INF_ConsulAction      ; "detected" | "install" | "provide" | "skip"
Var /GLOBAL INF_NomadAction
Var /GLOBAL INF_ConsulPath
Var /GLOBAL INF_NomadPath
Var /GLOBAL INF_HasWinget         ; "1" if winget on PATH, "0" otherwise

; ===================================================================
; Legacy broker detection — gated on ENABLE_LEGACY_BROKER.
; Wrapped so the function definitions disappear too when the flag
; is off (otherwise NSIS warns "function not referenced — zeroing
; code", and electron-builder treats warnings as errors).
; ===================================================================
!if ${ENABLE_LEGACY_BROKER} == 1

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

!endif ; ENABLE_LEGACY_BROKER (detect block)

; ===================================================================
; Detect Consul
; Sets $R0 = "1" if found, "0" otherwise.
; Sets $R1 = absolute path to consul.exe when found ("" otherwise).
; ===================================================================
Function DetectConsul
  StrCpy $R0 "0"
  StrCpy $R1 ""

  DetailPrint "DetectConsul: starting search..."

  ; 1. consul.exe on PATH
  nsExec::ExecToStack 'where consul.exe'
  Pop $R2
  Pop $R3
  ${If} $R2 == "0"
  ${AndIf} $R3 != ""
    Push $R3
    Call TrimFirstLine
    Pop $R1
    StrCpy $R0 "1"
    DetailPrint "DetectConsul: found via PATH at $R1"
    Return
  ${EndIf}
  DetailPrint "DetectConsul: not on PATH"

  ; 2. Default HashiCorp install paths
  IfFileExists "$PROGRAMFILES64\HashiCorp\Consul\consul.exe" consul_pf64 0
  Goto consul_check_pf32
  consul_pf64:
    StrCpy $R1 "$PROGRAMFILES64\HashiCorp\Consul\consul.exe"
    StrCpy $R0 "1"
    DetailPrint "DetectConsul: found at $R1"
    Return

  consul_check_pf32:
  IfFileExists "$PROGRAMFILES\HashiCorp\Consul\consul.exe" consul_pf32 0
  Goto consul_check_winget
  consul_pf32:
    StrCpy $R1 "$PROGRAMFILES\HashiCorp\Consul\consul.exe"
    StrCpy $R0 "1"
    DetailPrint "DetectConsul: found at $R1"
    Return

  consul_check_winget:
  ; 3. winget portable install (the user may have stripped PATH or
  ;    winget's Links folder isn't on PATH yet — NSIS captured the env
  ;    at launch time, before any winget install ran).
  ;    Two locations to check:
  ;      3a) %LOCALAPPDATA%\Microsoft\WinGet\Links\  — winget shim that
  ;          gets added to user PATH on first install.
  ;      3b) %LOCALAPPDATA%\Microsoft\WinGet\Packages\Hashicorp.Consul_* —
  ;          the actual extracted binary.  Globbed because the suffix
  ;          carries a source hash that may vary across machines.
  ;
  ;    All paths use NAMED LABELS — relative +N jumps inside ${If}
  ;    blocks are fragile because LogicLib injects hidden control flow.
  ReadEnvStr $R3 "LOCALAPPDATA"
  StrCmp $R3 "" consul_winget_done
  DetailPrint "DetectConsul: scanning winget under $R3\Microsoft\WinGet"

  ; 3a: Links shim
  IfFileExists "$R3\Microsoft\WinGet\Links\consul.exe" consul_winget_link 0
  Goto consul_check_pkgdir
  consul_winget_link:
    StrCpy $R1 "$R3\Microsoft\WinGet\Links\consul.exe"
    StrCpy $R0 "1"
    DetailPrint "DetectConsul: found via WinGet Links at $R1"
    Return

  consul_check_pkgdir:
  ; 3b: Package folder — glob Hashicorp.Consul_* and check each for consul.exe
  StrCpy $R4 "$R3\Microsoft\WinGet\Packages"
  FindFirst $R5 $R6 "$R4\Hashicorp.Consul_*"
  consul_winget_loop:
    StrCmp $R6 "" consul_winget_close
    DetailPrint "DetectConsul: trying $R4\$R6\consul.exe"
    IfFileExists "$R4\$R6\consul.exe" consul_winget_pkg 0
    Goto consul_winget_next
    consul_winget_pkg:
      StrCpy $R1 "$R4\$R6\consul.exe"
      StrCpy $R0 "1"
      FindClose $R5
      DetailPrint "DetectConsul: found in WinGet package at $R1"
      Return
    consul_winget_next:
    FindNext $R5 $R6
    Goto consul_winget_loop
  consul_winget_close:
  FindClose $R5

  consul_winget_done:
  DetailPrint "DetectConsul: not found in any known location"
FunctionEnd

; ===================================================================
; Detect Nomad
; Same shape as DetectConsul.
; ===================================================================
Function DetectNomad
  StrCpy $R0 "0"
  StrCpy $R1 ""

  DetailPrint "DetectNomad: starting search..."

  nsExec::ExecToStack 'where nomad.exe'
  Pop $R2
  Pop $R3
  ${If} $R2 == "0"
  ${AndIf} $R3 != ""
    Push $R3
    Call TrimFirstLine
    Pop $R1
    StrCpy $R0 "1"
    DetailPrint "DetectNomad: found via PATH at $R1"
    Return
  ${EndIf}
  DetailPrint "DetectNomad: not on PATH"

  IfFileExists "$PROGRAMFILES64\HashiCorp\Nomad\nomad.exe" nomad_pf64 0
  Goto nomad_check_pf32
  nomad_pf64:
    StrCpy $R1 "$PROGRAMFILES64\HashiCorp\Nomad\nomad.exe"
    StrCpy $R0 "1"
    DetailPrint "DetectNomad: found at $R1"
    Return

  nomad_check_pf32:
  IfFileExists "$PROGRAMFILES\HashiCorp\Nomad\nomad.exe" nomad_pf32 0
  Goto nomad_check_winget
  nomad_pf32:
    StrCpy $R1 "$PROGRAMFILES\HashiCorp\Nomad\nomad.exe"
    StrCpy $R0 "1"
    DetailPrint "DetectNomad: found at $R1"
    Return

  nomad_check_winget:
  ; 3. winget portable install — see DetectConsul for the rationale.
  ReadEnvStr $R3 "LOCALAPPDATA"
  StrCmp $R3 "" nomad_winget_done
  DetailPrint "DetectNomad: scanning winget under $R3\Microsoft\WinGet"

  IfFileExists "$R3\Microsoft\WinGet\Links\nomad.exe" nomad_winget_link 0
  Goto nomad_check_pkgdir
  nomad_winget_link:
    StrCpy $R1 "$R3\Microsoft\WinGet\Links\nomad.exe"
    StrCpy $R0 "1"
    DetailPrint "DetectNomad: found via WinGet Links at $R1"
    Return

  nomad_check_pkgdir:
  StrCpy $R4 "$R3\Microsoft\WinGet\Packages"
  FindFirst $R5 $R6 "$R4\Hashicorp.Nomad_*"
  nomad_winget_loop:
    StrCmp $R6 "" nomad_winget_close
    DetailPrint "DetectNomad: trying $R4\$R6\nomad.exe"
    IfFileExists "$R4\$R6\nomad.exe" nomad_winget_pkg 0
    Goto nomad_winget_next
    nomad_winget_pkg:
      StrCpy $R1 "$R4\$R6\nomad.exe"
      StrCpy $R0 "1"
      FindClose $R5
      DetailPrint "DetectNomad: found in WinGet package at $R1"
      Return
    nomad_winget_next:
    FindNext $R5 $R6
    Goto nomad_winget_loop
  nomad_winget_close:
  FindClose $R5

  nomad_winget_done:
  DetailPrint "DetectNomad: not found in any known location"
FunctionEnd

; ===================================================================
; Detect winget — needed for the "Install via winget" radio.
; Sets $INF_HasWinget = "1" when available, "0" otherwise.
; ===================================================================
Function DetectWinget
  StrCpy $INF_HasWinget "0"
  nsExec::ExecToStack 'where winget'
  Pop $R0
  Pop $R1
  ${If} $R0 == "0"
    StrCpy $INF_HasWinget "1"
  ${EndIf}
FunctionEnd

; ===================================================================
; TrimFirstLine helper — pops a multi-line string off the stack and
; pushes the first line back (CR/LF stripped).  Needed for `where ...`
; output which can return multiple paths.
; ===================================================================
Function TrimFirstLine
  Pop $R8       ; input
  StrLen $R9 $R8
  StrCpy $R7 0  ; index
  ${Do}
    ${If} $R7 >= $R9
      ${ExitDo}
    ${EndIf}
    StrCpy $R6 $R8 1 $R7
    ${If} $R6 == "$\r"
    ${OrIf} $R6 == "$\n"
      ${ExitDo}
    ${EndIf}
    IntOp $R7 $R7 + 1
  ${Loop}
  StrCpy $R8 $R8 $R7
  Push $R8
FunctionEnd

; ===================================================================
; Install Consul via winget (pinned to ${CONSUL_VER}).
; --source winget pins the lookup to the official winget repo and
; bypasses the msstore source — msstore requires interactive agreement
; acceptance per user context that --disable-interactivity can't handle.
;
; If winget returns non-zero we re-detect: a non-zero exit with the
; binary already on disk means "already installed" or "installed by
; another mechanism" — both are functionally success for our purpose.
; ===================================================================
Function InstallConsulViaWinget
  DetailPrint "Installing Consul ${CONSUL_VER} via winget..."
  nsExec::ExecToLog 'winget install --id ${CONSUL_WINGET_ID} \
    --version ${CONSUL_VER} \
    --source winget \
    --silent --accept-package-agreements --accept-source-agreements \
    --disable-interactivity'
  Pop $R0
  ${If} $R0 == "0"
    DetailPrint "Consul installed successfully."
    Return
  ${EndIf}

  DetailPrint "winget install Consul exit code: $R0 — re-detecting in case it's already on disk..."
  Call DetectConsul
  ${If} $R0 == "1"
    DetailPrint "Consul is on disk at $R1 — treating as installed."
    Return
  ${EndIf}

  ; Genuine failure — neither winget succeeded nor the binary exists.
  MessageBox MB_OK|MB_ICONEXCLAMATION \
    "winget install of Consul ${CONSUL_VER} failed and the binary is not on disk.$\n$\n\
    Install manually from:$\n\
    https://developer.hashicorp.com/consul/install$\n$\n\
    To diagnose, open elevated PowerShell and run:$\n\
    winget install --id ${CONSUL_WINGET_ID} --version ${CONSUL_VER} --source winget --verbose"
FunctionEnd

; ===================================================================
; Install Nomad via winget (pinned to ${NOMAD_VER}).
; --source winget — see InstallConsulViaWinget for rationale.
; Same "re-detect on failure" fallback so already-installed packages
; don't surface as errors.
; ===================================================================
Function InstallNomadViaWinget
  DetailPrint "Installing Nomad ${NOMAD_VER} via winget..."
  nsExec::ExecToLog 'winget install --id ${NOMAD_WINGET_ID} \
    --version ${NOMAD_VER} \
    --source winget \
    --silent --accept-package-agreements --accept-source-agreements \
    --disable-interactivity'
  Pop $R0
  ${If} $R0 == "0"
    DetailPrint "Nomad installed successfully."
    Return
  ${EndIf}

  DetailPrint "winget install Nomad exit code: $R0 — re-detecting in case it's already on disk..."
  Call DetectNomad
  ${If} $R0 == "1"
    DetailPrint "Nomad is on disk at $R1 — treating as installed."
    Return
  ${EndIf}

  MessageBox MB_OK|MB_ICONEXCLAMATION \
    "winget install of Nomad ${NOMAD_VER} failed and the binary is not on disk.$\n$\n\
    Install manually from:$\n\
    https://developer.hashicorp.com/nomad/install$\n$\n\
    To diagnose, open elevated PowerShell and run:$\n\
    winget install --id ${NOMAD_WINGET_ID} --version ${NOMAD_VER} --source winget --verbose"
FunctionEnd

; ===================================================================
; Save Consul / Nomad executable paths into settings.json.
; Mirrors SavePythonPathToSettings.  Skips fields that weren't picked.
; ===================================================================
Function SaveInfrastructurePathsToSettings
  StrCpy $R2 "$INSTDIR\resources\settings.json"
  IfFileExists $R2 0 inf_save_no_settings

  ; Build the powershell snippet — only set fields we have a value for.
  StrCpy $R3 ""
  ${If} $INF_ConsulPath != ""
    StrCpy $R3 "$$j | Add-Member -NotePropertyName ''consulPath'' -NotePropertyValue ''$INF_ConsulPath'' -Force; "
  ${EndIf}
  ${If} $INF_NomadPath != ""
    StrCpy $R3 "$R3$$j | Add-Member -NotePropertyName ''nomadPath'' -NotePropertyValue ''$INF_NomadPath'' -Force; "
  ${EndIf}

  ${If} $R3 == ""
    DetailPrint "No Consul/Nomad paths chosen — skipping settings.json update."
    Return
  ${EndIf}

  DetailPrint "Saving Consul/Nomad paths to settings.json..."
  nsExec::ExecToStack 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "\
    $$f = ''$R2''; \
    $$j = Get-Content $$f -Raw | ConvertFrom-Json; \
    $R3 \
    $$j | ConvertTo-Json -Depth 10 | Set-Content $$f -Encoding UTF8; \
    exit 0"'
  Pop $R0
  Pop $R1
  ${If} $R0 == "0"
    DetailPrint "Infrastructure paths saved."
  ${Else}
    DetailPrint "Warning: could not update settings.json (exit code $R0)."
  ${EndIf}
  Return

  inf_save_no_settings:
  DetailPrint "settings.json not found — skipping infrastructure path save."
FunctionEnd

; ===================================================================
; Infrastructure custom page — wiring helpers
; ===================================================================
Function INF_OnConsulRadio
  ${NSD_GetState} $INF_ConsulProvideRb $R0
  ${If} $R0 == ${BST_CHECKED}
    EnableWindow $INF_ConsulPathText 1
    EnableWindow $INF_ConsulBrowseBtn 1
  ${Else}
    EnableWindow $INF_ConsulPathText 0
    EnableWindow $INF_ConsulBrowseBtn 0
  ${EndIf}
FunctionEnd

Function INF_OnNomadRadio
  ${NSD_GetState} $INF_NomadProvideRb $R0
  ${If} $R0 == ${BST_CHECKED}
    EnableWindow $INF_NomadPathText 1
    EnableWindow $INF_NomadBrowseBtn 1
  ${Else}
    EnableWindow $INF_NomadPathText 0
    EnableWindow $INF_NomadBrowseBtn 0
  ${EndIf}
FunctionEnd

Function INF_OnBrowseConsul
  nsDialogs::SelectFileDialog open "" "Consul executable (consul.exe)|consul.exe|All files (*.*)|*.*"
  Pop $R0
  ${If} $R0 != ""
    ${NSD_SetText} $INF_ConsulPathText $R0
  ${EndIf}
FunctionEnd

Function INF_OnBrowseNomad
  nsDialogs::SelectFileDialog open "" "Nomad executable (nomad.exe)|nomad.exe|All files (*.*)|*.*"
  Pop $R0
  ${If} $R0 != ""
    ${NSD_SetText} $INF_NomadPathText $R0
  ${EndIf}
FunctionEnd

; ===================================================================
; Infrastructure custom page — Page Create
; Layout (top-to-bottom):
;   - Intro line
;   - --- Consul section ---
;       status label (detected path or "not found")
;       3 radios: Install via winget / Provide path / Skip
;       path text + Browse (enabled only when "Provide path" picked)
;   - --- Nomad section ---  (same shape)
; ===================================================================
Function INF_PageCreate
  nsDialogs::Create 1018
  Pop $INF_Dialog
  ${If} $INF_Dialog == error
    Abort
  ${EndIf}

  ; ---- Detection runs once at page entry ----
  Call DetectWinget

  Call DetectConsul
  ${If} $R0 == "1"
    StrCpy $INF_ConsulAction "detected"
    StrCpy $INF_ConsulPath $R1
  ${Else}
    StrCpy $INF_ConsulAction "skip"
    StrCpy $INF_ConsulPath ""
  ${EndIf}

  Call DetectNomad
  ${If} $R0 == "1"
    StrCpy $INF_NomadAction "detected"
    StrCpy $INF_NomadPath $R1
  ${Else}
    StrCpy $INF_NomadAction "skip"
    StrCpy $INF_NomadPath ""
  ${EndIf}

  ; Layout (dialog units, MUI client area is ~300x140):
  ;   intro              0u  - 18u   (h 18)
  ;   Consul groupbox    20u - 78u   (h 58)
  ;     status            +12u  (h 10)
  ;     radios            +24u  (h 11)
  ;     path + browse     +38u  (h 14)
  ;   Nomad groupbox     82u - 140u  (h 58)
  ;     same internal layout
  ;
  ; Radio captions kept short so they fit at any DPI; the pinned version
  ; is shown in the GroupBox title and re-iterated in the status line
  ; rather than crammed into the radio caption.

  ; ---- Intro ----
  ${NSD_CreateLabel} 0 0u 100% 18u \
    "Consul + Nomad are required for the Manager GUI to run services. \
For each, choose how to install or point at an existing executable."
  Pop $R0

  ; ====================== Consul section ======================
  ${NSD_CreateGroupBox} 0 20u 100% 58u "Consul (service discovery, pinned ${CONSUL_VER})"
  Pop $R0

  ${NSD_CreateLabel} 6u 32u 92% 10u ""
  Pop $INF_ConsulStatusLabel
  ${If} $INF_ConsulAction == "detected"
    ${NSD_SetText} $INF_ConsulStatusLabel "Detected at: $INF_ConsulPath"
  ${Else}
    ${NSD_SetText} $INF_ConsulStatusLabel "Not detected on this system."
  ${EndIf}

  ; Three radios — one per row would be cleaner but the page is short, so
  ; keep them inline with generous widths so captions don't crop.
  ;
  ; The FIRST radio of each section needs the WS_GROUP style so Windows
  ; treats Consul + Nomad as two separate sibling groups.  Without it,
  ; selecting any Nomad radio clears the Consul selection (and vice
  ; versa) because all 6 radios end up in one Win32 group.
  ;
  ; ${NSD_CreateFirstRadioButton} would do this for us, but the NSIS
  ; 3.0.4 that electron-builder bundles doesn't define it — so we add
  ; WS_GROUP by hand via SetWindowLong (GWL_STYLE = -16, WS_GROUP =
  ; 0x00020000).
  ${NSD_CreateRadioButton} 6u   44u 100u 11u "Install with winget"
  Pop $INF_ConsulInstallRb
  System::Call 'user32::GetWindowLongW(p$INF_ConsulInstallRb,i-16)i.r0'
  IntOp $0 $0 | 0x00020000
  System::Call 'user32::SetWindowLongW(p$INF_ConsulInstallRb,i-16,i$0)'
  ${NSD_CreateRadioButton} 110u 44u 90u  11u "Provide path"
  Pop $INF_ConsulProvideRb
  ${NSD_CreateRadioButton} 204u 44u 70u  11u "Skip"
  Pop $INF_ConsulSkipRb

  ${If} $INF_ConsulAction == "detected"
    ${NSD_SetState} $INF_ConsulSkipRb ${BST_CHECKED}
    EnableWindow $INF_ConsulInstallRb 0
    EnableWindow $INF_ConsulProvideRb 0
  ${ElseIf} $INF_HasWinget == "1"
    ${NSD_SetState} $INF_ConsulInstallRb ${BST_CHECKED}
  ${Else}
    ${NSD_SetState} $INF_ConsulProvideRb ${BST_CHECKED}
    EnableWindow $INF_ConsulInstallRb 0
  ${EndIf}

  ${NSD_OnClick} $INF_ConsulInstallRb INF_OnConsulRadio
  ${NSD_OnClick} $INF_ConsulProvideRb INF_OnConsulRadio
  ${NSD_OnClick} $INF_ConsulSkipRb    INF_OnConsulRadio

  ${NSD_CreateText}   6u  60u 230u 13u "$INF_ConsulPath"
  Pop $INF_ConsulPathText
  ${NSD_CreateButton} 240u 59u 30u  14u "..."
  Pop $INF_ConsulBrowseBtn
  ${NSD_OnClick} $INF_ConsulBrowseBtn INF_OnBrowseConsul
  Call INF_OnConsulRadio

  ; ====================== Nomad section ======================
  ${NSD_CreateGroupBox} 0 82u 100% 58u "Nomad (orchestrator, pinned ${NOMAD_VER})"
  Pop $R0

  ${NSD_CreateLabel} 6u 94u 92% 10u ""
  Pop $INF_NomadStatusLabel
  ${If} $INF_NomadAction == "detected"
    ${NSD_SetText} $INF_NomadStatusLabel "Detected at: $INF_NomadPath"
  ${Else}
    ${NSD_SetText} $INF_NomadStatusLabel "Not detected on this system."
  ${EndIf}

  ; First radio gets WS_GROUP via SetWindowLong so this section is its
  ; own Win32 radio group, independent of the Consul one above.  Same
  ; trick as the Consul section — see comment there for the why.
  ${NSD_CreateRadioButton} 6u   106u 100u 11u "Install with winget"
  Pop $INF_NomadInstallRb
  System::Call 'user32::GetWindowLongW(p$INF_NomadInstallRb,i-16)i.r0'
  IntOp $0 $0 | 0x00020000
  System::Call 'user32::SetWindowLongW(p$INF_NomadInstallRb,i-16,i$0)'
  ${NSD_CreateRadioButton} 110u 106u 90u  11u "Provide path"
  Pop $INF_NomadProvideRb
  ${NSD_CreateRadioButton} 204u 106u 70u  11u "Skip"
  Pop $INF_NomadSkipRb

  ${If} $INF_NomadAction == "detected"
    ${NSD_SetState} $INF_NomadSkipRb ${BST_CHECKED}
    EnableWindow $INF_NomadInstallRb 0
    EnableWindow $INF_NomadProvideRb 0
  ${ElseIf} $INF_HasWinget == "1"
    ${NSD_SetState} $INF_NomadInstallRb ${BST_CHECKED}
  ${Else}
    ${NSD_SetState} $INF_NomadProvideRb ${BST_CHECKED}
    EnableWindow $INF_NomadInstallRb 0
  ${EndIf}

  ${NSD_OnClick} $INF_NomadInstallRb INF_OnNomadRadio
  ${NSD_OnClick} $INF_NomadProvideRb INF_OnNomadRadio
  ${NSD_OnClick} $INF_NomadSkipRb    INF_OnNomadRadio

  ${NSD_CreateText}   6u  122u 230u 13u "$INF_NomadPath"
  Pop $INF_NomadPathText
  ${NSD_CreateButton} 240u 121u 30u  14u "..."
  Pop $INF_NomadBrowseBtn
  ${NSD_OnClick} $INF_NomadBrowseBtn INF_OnBrowseNomad
  Call INF_OnNomadRadio

  nsDialogs::Show
FunctionEnd

; ===================================================================
; Infrastructure custom page — Page Leave
; Resolves which radio is selected and validates "Provide path" choices.
; ===================================================================
Function INF_PageLeave
  ; ---- Consul ----
  ${NSD_GetState} $INF_ConsulInstallRb $R0
  ${NSD_GetState} $INF_ConsulProvideRb $R1
  ${NSD_GetState} $INF_ConsulSkipRb    $R2

  ${If} $R0 == ${BST_CHECKED}
    StrCpy $INF_ConsulAction "install"
    StrCpy $INF_ConsulPath ""    ; will be filled after winget install
  ${ElseIf} $R1 == ${BST_CHECKED}
    StrCpy $INF_ConsulAction "provide"
    ${NSD_GetText} $INF_ConsulPathText $INF_ConsulPath
    ${If} $INF_ConsulPath == ""
      MessageBox MB_OK|MB_ICONEXCLAMATION \
        "Please provide a path to consul.exe or pick another option."
      Abort
    ${EndIf}
    IfFileExists $INF_ConsulPath +3
      MessageBox MB_OK|MB_ICONEXCLAMATION \
        "consul.exe was not found at:$\n$INF_ConsulPath"
      Abort
  ${ElseIf} $R2 == ${BST_CHECKED}
    StrCpy $INF_ConsulAction "skip"
    StrCpy $INF_ConsulPath ""
  ${EndIf}

  ; ---- Nomad ----
  ${NSD_GetState} $INF_NomadInstallRb $R0
  ${NSD_GetState} $INF_NomadProvideRb $R1
  ${NSD_GetState} $INF_NomadSkipRb    $R2

  ${If} $R0 == ${BST_CHECKED}
    StrCpy $INF_NomadAction "install"
    StrCpy $INF_NomadPath ""
  ${ElseIf} $R1 == ${BST_CHECKED}
    StrCpy $INF_NomadAction "provide"
    ${NSD_GetText} $INF_NomadPathText $INF_NomadPath
    ${If} $INF_NomadPath == ""
      MessageBox MB_OK|MB_ICONEXCLAMATION \
        "Please provide a path to nomad.exe or pick another option."
      Abort
    ${EndIf}
    IfFileExists $INF_NomadPath +3
      MessageBox MB_OK|MB_ICONEXCLAMATION \
        "nomad.exe was not found at:$\n$INF_NomadPath"
      Abort
  ${ElseIf} $R2 == ${BST_CHECKED}
    StrCpy $INF_NomadAction "skip"
    StrCpy $INF_NomadPath ""
  ${EndIf}
FunctionEnd

; ===================================================================
; Legacy broker installers — gated on ENABLE_LEGACY_BROKER.
; DownloadFile is also wrapped because its only callers (InstallErlang /
; InstallRabbitMQ) sit inside this block.
; ===================================================================
!if ${ENABLE_LEGACY_BROKER} == 1

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

!endif ; ENABLE_LEGACY_BROKER (install block)

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
  nsExec::ExecToStack '"$MSB_PythonPath" -m pip install --upgrade "$R2[rabbitmq,web]"'
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
; Legacy ProcessHub install — gated on ENABLE_LEGACY_PROCESSHUB.
; Function definition wrapped (not just the call) so NSIS doesn't
; emit warning 6010 about an unreferenced function when the flag
; is off.
; ===================================================================
!if ${ENABLE_LEGACY_PROCESSHUB} == 1

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

!endif ; ENABLE_LEGACY_PROCESSHUB (install function)

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

    ; Detect ProcessHub (only when the legacy flow is enabled)
    !if ${ENABLE_LEGACY_PROCESSHUB} == 1
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
    !else
      ; ProcessHub deactivated — pretend "not found" so the status line
      ; only mentions MSB.
      StrCpy $R4 "1"
      StrCpy $R5 ""
    !endif

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

  ; Checkbox label adapts to ENABLE_LEGACY_PROCESSHUB (see top of file).
  ${NSD_CreateCheckBox} 0 0u 100% 12u "${MSB_CHECKBOX_LABEL}"
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
; customPageAfterChangeDir — register the custom wizard pages
;   1. Infrastructure (Consul + Nomad) — always shown
;   2. MicroserviceBase Python libraries — always shown
; ===================================================================
!macro customPageAfterChangeDir
  Page custom INF_PageCreate INF_PageLeave
  Page custom MSB_PageCreate MSB_PageLeave
!macroend

; ===================================================================
; customInstall — runs after app files are installed
; ===================================================================
!macro customInstall
  ; --- Consul + Nomad (current architecture) ---
  ${If} $INF_ConsulAction == "install"
    Call InstallConsulViaWinget
    ; Best-effort re-detect so we know the path winget put it at.
    Call DetectConsul
    ${If} $R0 == "1"
      StrCpy $INF_ConsulPath $R1
    ${EndIf}
  ${ElseIf} $INF_ConsulAction == "detected"
    DetailPrint "Consul already installed at: $INF_ConsulPath"
  ${ElseIf} $INF_ConsulAction == "provide"
    DetailPrint "Using user-provided Consul path: $INF_ConsulPath"
  ${Else}
    DetailPrint "Consul: skipped (user will install later)."
  ${EndIf}

  ${If} $INF_NomadAction == "install"
    Call InstallNomadViaWinget
    Call DetectNomad
    ${If} $R0 == "1"
      StrCpy $INF_NomadPath $R1
    ${EndIf}
  ${ElseIf} $INF_NomadAction == "detected"
    DetailPrint "Nomad already installed at: $INF_NomadPath"
  ${ElseIf} $INF_NomadAction == "provide"
    DetailPrint "Using user-provided Nomad path: $INF_NomadPath"
  ${Else}
    DetailPrint "Nomad: skipped (user will install later)."
  ${EndIf}

  Call SaveInfrastructurePathsToSettings

  ; --- Legacy broker path (Erlang + RabbitMQ) ---
  ; Deactivated post-migration.  Set ENABLE_LEGACY_BROKER=1 at the top
  ; of this file to re-activate alongside the Consul/Nomad path.
  !if ${ENABLE_LEGACY_BROKER} == 1
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
  !endif

  ; --- Python libraries (MicroserviceBase, +ProcessHub when legacy flow on) ---
  ${If} $MSB_DoInstall == "1"
    Call InstallMicroserviceBase
    !if ${ENABLE_LEGACY_PROCESSHUB} == 1
      Call InstallProcessHub
    !endif
  ${EndIf}
  ${If} $MSB_PythonPath != ""
    Call SavePythonPathToSettings
  ${EndIf}
!macroend
