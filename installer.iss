; HWInfo Monitor - Inno Setup Installer Script

#define AppName "HWInfo Monitor"
#ifndef AppVersion
#define AppVersion "0.0.12"
#endif
#define AppPublisher "ISNET"
#define AppExeName "HWInfoMonitor.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf64}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=output
OutputBaseFilename=HWInfoMonitor_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
MinVersion=10.0
UninstallDisplayIcon={app}\{#AppExeName}
DisableWelcomePage=no
DisableDirPage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\HWInfoMonitor\HWInfoMonitor.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\HWInfoMonitor\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "stress_worker.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "stress_worker.py"; DestDir: "{app}\_internal"; Flags: ignoreversion

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"; ValueType: string; ValueName: "{app}\{#AppExeName}"; ValueData: "RUNASADMIN"; Flags: uninsdeletevalue

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]

// ── Admin elevation check ─────────────────────────────────────
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  InstallerPath: String;
begin
  Result := True;
  if not IsAdmin() then
  begin
    InstallerPath := ExpandConstant('{srcexe}');
    Exec('powershell.exe',
      '-NoProfile -ExecutionPolicy Bypass -Command "Start-Process ''"' + InstallerPath + '"'' -Verb RunAs"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Result := False;
  end;
end;

// ── Auto-uninstall previous version ───────────────────────────
function GetUninstallString(): String;
var
  RegKey: String;
  UninstStr: String;
begin
  RegKey := 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1';
  UninstStr := '';
  if not RegQueryStringValue(HKLM, RegKey, 'UninstallString', UninstStr) then
    RegQueryStringValue(HKCU, RegKey, 'UninstallString', UninstStr);
  Result := UninstStr;
end;

function IsAlreadyInstalled(): Boolean;
begin
  Result := GetUninstallString() <> '';
end;

procedure UninstallPrevious();
var
  UninstStr: String;
  ResultCode: Integer;
begin
  UninstStr := GetUninstallString();
  if UninstStr = '' then Exit;

  Exec('powershell.exe',
    '-NoProfile -WindowStyle Hidden -Command "Stop-Process -Name ''HWInfoMonitor'' -Force -ErrorAction SilentlyContinue; Start-Sleep 2"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  UninstStr := RemoveQuotes(UninstStr);
  Exec(UninstStr, '/SILENT /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// ── .NET 10 check ─────────────────────────────────────────────
// NOTE: LHMBridge is self-contained (no .NET install required).
// This check is kept as informational only and will not block install.
function IsDotNet10Installed(): Boolean;
var
  ResultCode: Integer;
  TempFile: String;
  FileContent: TArrayOfString;
  I: Integer;
begin
  Result := False;
  TempFile := ExpandConstant('{tmp}\dotnetcheck.txt');
  Exec('cmd.exe',
    '/C dotnet --list-runtimes > "' + TempFile + '" 2>&1',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if LoadStringsFromFile(TempFile, FileContent) then
  begin
    for I := 0 to GetArrayLength(FileContent) - 1 do
    begin
      if (Pos('Microsoft.NETCore.App 10.', FileContent[I]) > 0) or
         (Pos('Microsoft.WindowsDesktop.App 10.', FileContent[I]) > 0) then
      begin
        Result := True;
        Exit;
      end;
    end;
  end;
end;

// ── Main install steps ────────────────────────────────────────
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    if IsAlreadyInstalled() then
      UninstallPrevious();
    // LHMBridge is self-contained — no .NET check needed
  end;
end;
