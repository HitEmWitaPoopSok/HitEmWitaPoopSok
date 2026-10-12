; Inno Setup script -- builds JARVIS-Setup-<version>.exe.
; Run by windows/build.ps1 after it has staged everything under build\stage.
;   iscc /DAppVersion=1.0.0 windows\jarvis.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C1D2F5B-6C0E-4F0A-9B52-4A1F3E7D9A11}
AppName=JARVIS
AppVersion={#AppVersion}
AppPublisher=HitEmWitaPoopSok
DefaultDirName={autopf}\JARVIS
DefaultGroupName=JARVIS
DisableProgramGroupPage=yes
; Per-user install: no administrator prompt, and the program folder stays
; writable so the embedded Python can write its bytecode caches.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\out
OutputBaseFilename=JARVIS-Setup-{#AppVersion}
SetupIconFile=jarvis.ico
UninstallDisplayIcon={app}\JARVIS.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "browser"; Description: "Download the headless browser JARVIS uses to read web pages (about 150 MB, needs internet)"; GroupDescription: "Optional components:"

[Files]
Source: "..\build\stage\JARVIS.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\stage\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\stage\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\JARVIS"; Filename: "{app}\JARVIS.exe"
Name: "{group}\Stop JARVIS"; Filename: "{app}\JARVIS.exe"; Parameters: "--stop"
Name: "{group}\JARVIS settings and data"; Filename: "{userappdata}\JARVIS"
Name: "{autodesktop}\JARVIS"; Filename: "{app}\JARVIS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\python\python.exe"; Parameters: "-m playwright install chromium"; StatusMsg: "Downloading the browser component..."; Flags: runhidden; Tasks: browser
Filename: "{app}\JARVIS.exe"; Description: "Start JARVIS now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\JARVIS.exe"; Parameters: "--stop"; Flags: runhidden skipifdoesntexist; RunOnceId: "StopJarvis"

[Code]
function ClaudeOnPath(): Boolean;
var
  Dummy: String;
begin
  Result := FileSearch('claude.exe', GetEnv('PATH')) <> '';
  if not Result then Result := FileSearch('claude.cmd', GetEnv('PATH')) <> '';
  if not Result then Result := FileSearch('claude.bat', GetEnv('PATH')) <> '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not WizardSilent) and (not ClaudeOnPath()) then
    MsgBox('Claude Code was not found on this PC.' + #13#10 + #13#10 +
           'JARVIS thinks with Claude Code, on your Claude subscription. After this ' +
           'installer finishes: install Claude Code (docs.claude.com/en/docs/claude-code/setup), ' +
           'run "claude" once in a terminal to log in, then start JARVIS.' + #13#10 + #13#10 +
           'You also need a Fish Audio API key for his voice (fish.audio); ' +
           'JARVIS will ask for it in his settings.', mbInformation, MB_OK);
end;
