[Setup]
AppName=Azalea Media Server
AppVersion=1.3a
AppPublisher=Ethan Martin
AppPublisherURL=https://github.com/yuckdevchan
AppComments=The media server solution that cares.
DisableDirPage=auto
DefaultDirName={autopf}\AzaleaMediaServer
DefaultGroupName=Azalea
WizardImageFile=wizard_image.png
WizardSmallImageFile=wizard_small_image.png
WizardImageStretch=yes
WizardStyle=modern dark polar includetitlebar
UninstallDisplayIcon={app}\app_icon.ico
Compression=lzma2/max
LZMAUseSeparateProcess=yes
LZMADictionarySize=153600
LZMABlockSize=153600
SolidCompression=yes
OutputDir=.
OutputBaseFilename=Azalea 1.3a Setup
SetupIconFile=app_icon.ico
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
AllowNoIcons=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
AlwaysShowComponentsList=yes
CloseApplications=yes

[Components]
Name: "core"; Description: "Azalea Core Server Files"; Types: full custom compact; Flags: fixed
Name: "docs"; Description: "Azalea Documentation Files"; Types: full custom compact;
Name: "cavatina"; Description: "Include Beethoven Op. 130 Cavatina MP3"; Types: full custom;
Name: "src"; Description: "Include source code"; Types: full custom;
Name: "web_component"; Description: "Install Azalea Web Component"; Types: full custom compact
Name: "vlc_component"; Description: "Download and Install VLC Media Player"; Types: full; ExtraDiskSpaceRequired: 44040192
Name: "node_setup"; Description: "Download and Install Node.js v24.18.0 for Web UI"; Types: full custom; ExtraDiskSpaceRequired: 60000000

Name: "python_setup"; Description: "Python Environment Configurations"; Types: full custom
Name: "python_setup\download"; Description: "Install Python locally into Azalea directory"; Types: full; Flags: exclusive; ExtraDiskSpaceRequired: 30774112
Name: "python_setup\manual"; Description: "Choose Existing Python.exe Manually"; Types: custom; Flags: exclusive
Name: "python_setup\none"; Description: "Don't install Python"; Types: compact; Flags: exclusive

Name: "ytdlp_setup"; Description: "yt-dlp Configurations"; Types: full custom
Name: "ytdlp_setup\download"; Description: "Download yt-dlp locally into Azalea directory"; Types: full; Flags: exclusive; ExtraDiskSpaceRequired: 15000000
Name: "ytdlp_setup\manual"; Description: "Choose Existing yt-dlp.exe Manually"; Types: custom; Flags: exclusive
Name: "ytdlp_setup\none"; Description: "Don't install yt-dlp"; Types: compact; Flags: exclusive

Name: "startmenu"; Description: "Start Menu Folder Options"; Types: full custom compact
Name: "startmenu\default"; Description: "Create Start Menu Folder (Default)"; Types: full compact; Flags: exclusive
Name: "startmenu\custom"; Description: "Create Start Menu Folder with Custom Name..."; Types: custom; Flags: exclusive
Name: "startmenu\none"; Description: "Don't create a Start Menu Folder"; Types: custom; Flags: exclusive

Name: "desktop_shortcut"; Description: "Create Desktop Shortcut"; Types: full custom

[Files]
Source: "https://www.python.org/ftp/python/3.14.6/python-3.14.6-amd64.zip"; DestDir: "{app}"; DestName: "python_full.zip"; Flags: external download ignoreversion; ExternalSize: 36547413; Check: ShouldDownloadPython

Source: "https://nodejs.org/dist/v24.18.0/node-v24.18.0-x64.msi"; DestDir: "{app}"; DestName: "node_installer.msi"; Flags: external download ignoreversion; ExternalSize: 32874496; Check: WizardIsComponentSelected('node_setup')

Source: "https://get.videolan.org/vlc/3.0.23/win64/vlc-3.0.23-win64.exe"; DestDir: "{app}"; DestName: "vlc_installer.exe"; Flags: external download ignoreversion; ExternalSize: 44040192; Check: WizardIsComponentSelected('vlc_component')

Source: "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"; DestDir: "{app}"; DestName: "yt-dlp.exe"; Flags: external download ignoreversion; ExternalSize: 18202192; Check: ShouldDownloadYtdlp

Source: "main.py"; DestDir: "{app}"; Components: core
Source: "requirements.txt"; DestDir: "{app}"; Components: core
Source: "app_icon.ico"; DestDir: "{app}"; Components: core
Source: "core.toml"; DestDir: "{app}"; Components: core
Source: "default_config.toml"; DestDir: "{app}"; Components: core
Source: "config.py"; DestDir: "{app}"; Components: core
Source: "db.py"; DestDir: "{app}"; Components: core
Source: "discord_rpc.py"; DestDir: "{app}"; Components: core
Source: "library.py"; DestDir: "{app}"; Components: core
Source: "metadata.py"; DestDir: "{app}"; Components: core
Source: "quart_management_ui.py"; DestDir: "{app}"; Components: core
Source: "quart_subsonic_api.py"; DestDir: "{app}"; Components: core
Source: "quart_azalea_api.py"; DestDir: "{app}"; Components: core
Source: "subsonic.py"; DestDir: "{app}"; Components: core
Source: "utils.py"; DestDir: "{app}"; Components: core
Source: "ws.py"; DestDir: "{app}"; Components: core
Source: "cleaning.py"; DestDir: "{app}"; Components: core
Source: "downloader.py"; DestDir: "{app}"; Components: core
Source: "imaging.py"; DestDir: "{app}"; Components: core
Source: "qt_ui.py"; DestDir: "{app}"; Components: core
Source: "templates\*"; DestDir: "{app}\templates"; Flags: recursesubdirs createallsubdirs; Components: core
Source: "static\*"; DestDir: "{app}\static"; Flags: recursesubdirs createallsubdirs; Components: core

Source: "assets\cavatina.mp3"; DestDir: "{app}\builtin"; Flags: recursesubdirs createallsubdirs; Components: cavatina

Source: "src\*"; DestDir: "{app}\Source Code"; Flags: recursesubdirs createallsubdirs; Components: src

Source: "docs\*"; DestDir: "{app}\docs"; Flags: recursesubdirs createallsubdirs; Components: docs

Source: "build\*"; DestDir: "{app}\build"; Flags: recursesubdirs createallsubdirs; Components: web_component

[Icons]
Name: "{commonprograms}\{code:GetCustomGroupName}\Azalea Media Server"; Filename: "{code:GetPythonPath}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"; Check: "ShouldRunPip and ShouldRunStartMenu"
Name: "{commonprograms}\{code:GetCustomGroupName}\Azalea Application Directory"; Filename: "{app}"; Check: "not ShouldRunPip and ShouldRunStartMenu"
Name: "{autodesktop}\Azalea Media Server"; Filename: "{code:GetPythonPath}"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app_icon.ico"; Check: ShouldRunPip; Components: desktop_shortcut

[Run]
Filename: "powershell.exe"; Parameters: "-Command ""Expand-Archive -Path '{app}\python_full.zip' -DestinationPath '{app}\python' -Force"""; StatusMsg: "Extracting isolated Python runtime environment..."; Flags: runhidden; Check: ShouldDownloadPython
Filename: "{app}\python\python.exe"; Parameters: "-m ensurepip --upgrade"; StatusMsg: "Bootstrapping pip into localized Python container..."; Flags: runhidden; Check: ShouldDownloadPython
Filename: "{code:GetPythonPath}"; Parameters: "-m pip install --no-cache-dir --force-reinstall --only-binary=:all: -r ""{app}\requirements.txt"""; StatusMsg: "Installing application dependencies..."; Flags: runhidden; Check: ShouldRunPip
Filename: "{cmd}"; Parameters: "/c del ""{app}\python_full.zip"""; Flags: runhidden; Check: ShouldDownloadPython
Filename: "{app}\vlc_installer.exe"; Parameters: "/S"; StatusMsg: "Installing VLC Media Player..."; Flags: runhidden; Check: WizardIsComponentSelected('vlc_component')
Filename: "{cmd}"; Parameters: "/c del ""{app}\vlc_installer.exe"""; Flags: runhidden; Check: WizardIsComponentSelected('vlc_component')
Filename: "msiexec.exe"; Parameters: "/i ""{app}\node_installer.msi"" /quiet INSTALLDIR=""{app}\node"" ADDLOCAL=ALL"; StatusMsg: "Installing Node.js runtime environment for Web UI..."; Flags: runhidden; Check: WizardIsComponentSelected('node_setup')
Filename: "{cmd}"; Parameters: "/c del ""{app}\node_installer.msi"""; Flags: runhidden; Check: WizardIsComponentSelected('node_setup')

[Messages]
FinishedLabel=The Azalea Media Server is now installed on your computer.%n%nEnjoy your music and enjoy your new software!%n%nRemember:%nAzalea is free software - 'free' as in freedom or free speech.

[Code]
var
  ManualPythonPath: String;
  ManualYtdlpPath: String;
  CustomGroupName: String;
  CustomQueryPage: TInputQueryWizardPage;

  StartAzaleaCheck: TNewCheckBox;
  OpenWebUiCheck: TNewCheckBox;
  OpenMgmtUiCheck: TNewCheckBox;

const
  AppRegKey = 'Software\AzaleaMediaServer';
  WM_SETTINGCHANGE = $001A;

procedure SendMessage(hWnd: Longint; Msg: Longint; wParam: Longint; lParam: Longint);
  external 'SendMessageW@user32.dll stdcall';

procedure BroadcastEnvChange;
begin
  SendMessage(HWND_BROADCAST, WM_SETTINGCHANGE, 0, 0);
end;

procedure CreateAzaleaCmd(AppDir: String);
var
  Script: String;
begin
  Script :=
    '@echo off' + #13#10 +
    'set "AZALEA_DIR=%~dp0"' + #13#10 +
    'if exist "%AZALEA_DIR%python\python.exe" (' + #13#10 +
    '    "%AZALEA_DIR%python\python.exe" "%AZALEA_DIR%main.py" %*' + #13#10 +
    ') else (' + #13#10 +
    '    python "%AZALEA_DIR%main.py" %*' + #13#10 +
    ')';
  SaveStringToFile(AppDir + '\azalea.cmd', Script, False);
end;

procedure AddAppToPath(AppDir: String);
var
  OrigPath: String;
  LowerPath: String;
begin
  if RegQueryStringValue(HKEY_LOCAL_MACHINE, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', OrigPath) then
  begin
    LowerPath := LowerCase(OrigPath);
    if (LowerPath <> LowerCase(AppDir) + ';') and
       (Pos(LowerCase(';' + AppDir + ';'), LowerPath) = 0) and
       (Pos(LowerCase(';' + AppDir), LowerPath) = 0) then
    begin
      OrigPath := OrigPath + ';' + AppDir;
      RegWriteExpandStringValue(HKEY_LOCAL_MACHINE, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', OrigPath);
      BroadcastEnvChange;
    end;
  end;
end;

procedure RemoveAppFromPath(AppDir: String);
var
  CurPath: String;
begin
  if RegQueryStringValue(HKEY_LOCAL_MACHINE, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', CurPath) then
  begin
    StringChange(CurPath, AppDir + ';', '');
    StringChange(CurPath, ';' + AppDir, '');
    if Pos(LowerCase(AppDir), LowerCase(CurPath)) = 0 then
    begin
      RegWriteExpandStringValue(HKEY_LOCAL_MACHINE, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', CurPath);
    end;
  end;
end;

procedure InitializeWizard;
var
  SavedStr: String;
begin
  ManualPythonPath := '';
  ManualYtdlpPath := '';
  CustomGroupName := 'Azalea';

  if RegQueryStringValue(HKEY_LOCAL_MACHINE, AppRegKey, 'ManualPythonPath', SavedStr) then
    ManualPythonPath := SavedStr;

  if RegQueryStringValue(HKEY_LOCAL_MACHINE, AppRegKey, 'ManualYtdlpPath', SavedStr) then
    ManualYtdlpPath := SavedStr;

  if RegQueryStringValue(HKEY_LOCAL_MACHINE, AppRegKey, 'CustomGroupName', SavedStr) then
    CustomGroupName := SavedStr;

  CustomQueryPage := CreateInputQueryPage(wpSelectComponents,
    'Custom Start Menu Folder',
    'Enter the name for your Start Menu program group:',
    'Please specify the directory name below, then click Next to continue.');

  CustomQueryPage.Add('Folder Name:', False);

  CustomQueryPage.Values[0] := CustomGroupName;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    RegWriteStringValue(HKEY_LOCAL_MACHINE, AppRegKey, 'ManualPythonPath', ManualPythonPath);
    RegWriteStringValue(HKEY_LOCAL_MACHINE, AppRegKey, 'ManualYtdlpPath', ManualYtdlpPath);
    RegWriteStringValue(HKEY_LOCAL_MACHINE, AppRegKey, 'CustomGroupName', CustomGroupName);

    CreateAzaleaCmd(ExpandConstant('{app}'));

    AddAppToPath(ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemoveAppFromPath(ExpandConstant('{app}'));
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = CustomQueryPage.ID then
  begin
    Result := not WizardIsComponentSelected('startmenu\custom');
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  FileName: String;
begin
  Result := True;

  if (CurPageID = wpSelectComponents) then
  begin
    if Result and WizardIsComponentSelected('python_setup\manual') then
    begin
      if GetOpenFileName('Select your existing python.exe...', FileName, '', 'Python Executable (python.exe)|python.exe', 'exe') then
      begin
        ManualPythonPath := FileName;
      end
      else
      begin
        MsgBox('You must select a valid python.exe to use the manual option.', mbError, MB_OK);
        Result := False;
      end;
    end;

    if Result and WizardIsComponentSelected('ytdlp_setup\manual') then
    begin
      if GetOpenFileName('Select your existing yt-dlp.exe...', FileName, '', 'yt-dlp Executable (yt-dlp.exe)|yt-dlp.exe', 'exe') then
      begin
        ManualYtdlpPath := FileName;
      end
      else
      begin
        MsgBox('You must select a valid yt-dlp.exe to use the manual option.', mbError, MB_OK);
        Result := False;
      end;
    end;
  end;

  if CurPageID = CustomQueryPage.ID then
  begin
    if Trim(CustomQueryPage.Values[0]) <> '' then
      CustomGroupName := Trim(CustomQueryPage.Values[0])
    else
      CustomGroupName := 'Azalea';
  end;
end;

function GetPythonPath(Param: String): String;
begin
  if WizardIsComponentSelected('python_setup\manual') and (ManualPythonPath <> '') then
    Result := ManualPythonPath
  else if WizardIsComponentSelected('python_setup\download') then
    Result := ExpandConstant('{app}\python\python.exe')
  else if FileExists(ExpandConstant('{app}\python\python.exe')) then
    Result := ExpandConstant('{app}\python\python.exe')
  else
    Result := '';
end;

function GetCustomGroupName(Param: String): String;
begin
  Result := CustomGroupName;
end;

function ShouldRunPip: Boolean;
begin
  Result := WizardIsComponentSelected('python_setup\download') or
            (ManualPythonPath <> '') or
            FileExists(ExpandConstant('{app}\python\python.exe'));
end;

function ShouldRunStartMenu: Boolean;
begin
  Result := WizardIsComponentSelected('startmenu\default') or WizardIsComponentSelected('startmenu\custom');
end;

function ShouldDownloadPython: Boolean;
begin
  Result := WizardIsComponentSelected('python_setup\download');
end;

function ShouldDownloadYtdlp: Boolean;
begin
  Result := WizardIsComponentSelected('ytdlp_setup\download');
end;

procedure StartAzaleaClick(Sender: TObject);
begin
  OpenMgmtUiCheck.Enabled := StartAzaleaCheck.Checked;

  if WizardIsComponentSelected('web_component') then
    OpenWebUiCheck.Enabled := StartAzaleaCheck.Checked;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    StartAzaleaCheck := TNewCheckBox.Create(WizardForm);
    StartAzaleaCheck.Parent := WizardForm.FinishedPage;
    StartAzaleaCheck.Left := WizardForm.FinishedLabel.Left;
    StartAzaleaCheck.Top := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height + ScaleY(20);
    StartAzaleaCheck.Width := WizardForm.FinishedLabel.Width;
    StartAzaleaCheck.Height := ScaleY(20);
    StartAzaleaCheck.Caption := 'Start Azalea Media Server';
    StartAzaleaCheck.Checked := True;
    StartAzaleaCheck.OnClick := @StartAzaleaClick;

    OpenMgmtUiCheck := TNewCheckBox.Create(WizardForm);
    OpenMgmtUiCheck.Parent := WizardForm.FinishedPage;
    OpenMgmtUiCheck.Left := StartAzaleaCheck.Left + ScaleX(20);
    OpenMgmtUiCheck.Top := StartAzaleaCheck.Top + ScaleY(25);
    OpenMgmtUiCheck.Width := WizardForm.FinishedLabel.Width - ScaleX(20);
    OpenMgmtUiCheck.Height := ScaleY(20);
    OpenMgmtUiCheck.Caption := 'Open Management UI (http://localhost:3443)';
    OpenMgmtUiCheck.Checked := True;

    OpenWebUiCheck := TNewCheckBox.Create(WizardForm);
    OpenWebUiCheck.Parent := WizardForm.FinishedPage;
    OpenWebUiCheck.Left := OpenMgmtUiCheck.Left;
    OpenWebUiCheck.Top := OpenMgmtUiCheck.Top + ScaleY(25);
    OpenWebUiCheck.Width := OpenMgmtUiCheck.Width;
    OpenWebUiCheck.Height := ScaleY(20);
    OpenWebUiCheck.Caption := 'Open Web UI (http://localhost:3000)';
    OpenWebUiCheck.Checked := True;

    if not WizardIsComponentSelected('web_component') then
    begin
      OpenWebUiCheck.Visible := False;
      OpenWebUiCheck.Enabled := False;
    end;

    StartAzaleaClick(StartAzaleaCheck);
  end;
end;

procedure DeinitializeSetup;
var
  ErrorCode: Integer;
  PythonExe: String;
  AppDir: String;
begin
  if Assigned(StartAzaleaCheck) and StartAzaleaCheck.Checked and ShouldRunPip then
  begin
    PythonExe := GetPythonPath('');
    AppDir := ExpandConstant('{app}');

    if PythonExe <> '' then
    begin
      ShellExec('', PythonExe, '"' + AppDir + '\main.py"', AppDir, SW_SHOWNORMAL, ewNoWait, ErrorCode);
      Sleep(500);

      if OpenMgmtUiCheck.Checked and OpenMgmtUiCheck.Enabled then
      begin
        ShellExec('', 'http://localhost:3443', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
      end;

      if OpenWebUiCheck.Checked and OpenWebUiCheck.Enabled then
      begin
        ShellExec('', 'http://localhost:3000', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
      end;
    end;
  end;
end;

[InstallDelete]
Type: filesandordirs; Name: "{app}\client"
Type: files; Name: "{app}\index.js"

Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\templates\__pycache__"

[Registry]
Root: HKLM; Subkey: "Software\AzaleaMediaServer"; Flags: uninsdeletekey

[UninstallDelete]
Type: files; Name: "{app}\azalea.cmd"
