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
Name: "startup"; Description: "Start JARVIS quietly when I sign in to Windows (so my phone can reach him; no browser opens)"; GroupDescription: "Optional components:"
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

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "JARVIS"; ValueData: """{app}\JARVIS.exe"" --no-browser"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\python\python.exe"; Parameters: "-m playwright install chromium"; StatusMsg: "Downloading the browser component..."; Flags: runhidden; Tasks: browser
Filename: "{app}\JARVIS.exe"; Description: "Start JARVIS now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\JARVIS.exe"; Parameters: "--stop"; Flags: runhidden skipifdoesntexist; RunOnceId: "StopJarvis"

[Code]
var
  KeyPage: TInputQueryWizardPage;

procedure InitializeWizard();
begin
  KeyPage := CreateInputQueryPage(wpSelectTasks,
    'Your voice',
    'Fish Audio API key',
    'JARVIS speaks through Fish Audio (fish.audio), which needs an API key. ' +
    'Paste yours below and the installer will save it for you. You can also ' +
    'leave it blank and enter it later inside JARVIS.');
  KeyPage.Add('Fish Audio API key:', True);
  KeyPage.Add('What should JARVIS call you? (optional)', False);
  KeyPage.Values[0] := ExpandConstant('{param:fishkey|}');
  KeyPage.Values[1] := ExpandConstant('{param:username|}');
end;

function CleanValue(const S: String): String;
begin
  Result := Trim(S);
end;

function ValueHasForbiddenCharacter(const S: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to Length(S) do
    if (Ord(S[I]) < 32) or (S[I] = '"') or (S[I] = '''') then
      Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = KeyPage.ID then
  begin
    if ValueHasForbiddenCharacter(CleanValue(KeyPage.Values[0])) or
       (Pos(' ', CleanValue(KeyPage.Values[0])) > 0) then
    begin
      MsgBox('The API key should be one unbroken string with no spaces or quotes. ' +
             'Copy it again from fish.audio, or leave the box empty.', mbError, MB_OK);
      Result := False;
    end
    else if ValueHasForbiddenCharacter(CleanValue(KeyPage.Values[1])) or
            (Length(CleanValue(KeyPage.Values[1])) > 60) then
    begin
      MsgBox('Please use a short name without quotes.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

{ Sets Key=Value in Lines, replacing an existing Key= line or adding one. }
procedure SetEnvLine(var Lines: TArrayOfString; const Key, Value: String);
var
  I, N: Integer;
begin
  for I := 0 to GetArrayLength(Lines) - 1 do
    if Pos(Key + '=', Lines[I]) = 1 then
    begin
      Lines[I] := Key + '=' + Value;
      Exit;
    end;
  N := GetArrayLength(Lines);
  SetArrayLength(Lines, N + 1);
  Lines[N] := Key + '=' + Value;
end;

procedure SaveSettings;
var
  Dir, EnvFile: String;
  Lines: TArrayOfString;
  FishKey, UserName: String;
begin
  if WizardSilent then
  begin
    FishKey := CleanValue(ExpandConstant('{param:fishkey|}'));
    UserName := CleanValue(ExpandConstant('{param:username|}'));
  end
  else
  begin
    FishKey := CleanValue(KeyPage.Values[0]);
    UserName := CleanValue(KeyPage.Values[1]);
  end;
  if (FishKey = '') and (UserName = '') then Exit;

  Dir := ExpandConstant('{userappdata}\JARVIS');
  ForceDirectories(Dir);
  EnvFile := Dir + '\.env';
  { Keep whatever is already there; otherwise start from the shipped template. }
  if not FileExists(EnvFile) then
    LoadStringsFromFile(ExpandConstant('{app}\app\.env.example'), Lines)
  else
    LoadStringsFromFile(EnvFile, Lines);
  if FishKey <> '' then SetEnvLine(Lines, 'FISH_API_KEY', FishKey);
  if UserName <> '' then SetEnvLine(Lines, 'USER_NAME', UserName);
  SaveStringsToUTF8File(EnvFile, Lines, False);
end;

{ An upgrade cannot replace python.exe and its DLLs while the old JARVIS server
  is running from the install folder. End every process that runs from there. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Dir, Params: String;
  ResultCode: Integer;
begin
  Result := '';
  Dir := WizardDirValue;
  if DirExists(Dir) then
  begin
    StringChangeEx(Dir, '''', '''''', True);
    Params := '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process | Where-Object { $_.Path -and ' +
              '$_.Path.StartsWith(''' + Dir + '\'', [StringComparison]::OrdinalIgnoreCase) } | ' +
              'Stop-Process -Force -ErrorAction SilentlyContinue"';
    Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1500);
  end;
end;

function ClaudeOnPath(): Boolean;
begin
  Result := FileSearch('claude.exe', GetEnv('PATH')) <> '';
  if not Result then Result := FileSearch('claude.cmd', GetEnv('PATH')) <> '';
  if not Result then Result := FileSearch('claude.bat', GetEnv('PATH')) <> '';
end;

function ChromeInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf64}\Google\Chrome\Application\chrome.exe')) or
            FileExists(ExpandConstant('{commonpf32}\Google\Chrome\Application\chrome.exe')) or
            FileExists(ExpandConstant('{localappdata}\Google\Chrome\Application\chrome.exe'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Missing: String;
begin
  if CurStep = ssPostInstall then
  begin
    SaveSettings;
    if not WizardSilent then
    begin
      Missing := '';
      if not ClaudeOnPath() then
        Missing := Missing + #13#10 + '  - Claude Code: install it from docs.claude.com/en/docs/claude-code/setup, ' +
                   'then run "claude" once in a terminal to log in. It needs Git for Windows.';
      if not ChromeInstalled() then
        Missing := Missing + #13#10 + '  - Google Chrome: JARVIS listens through Chrome, other browsers cannot hear you.';
      if Missing <> '' then
        MsgBox('JARVIS is installed, but these are still needed before he can work:' +
               Missing, mbInformation, MB_OK);
    end;
  end;
end;
