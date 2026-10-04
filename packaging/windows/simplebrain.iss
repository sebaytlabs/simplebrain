; Inno Setup installer: iscc /DAppVersion=0.1.0 packaging\windows\simplebrain.iss
; Per-user install (no admin prompt); re-running a newer installer updates in place.
[Setup]
AppId={{CD3638FD-1047-479E-9E30-3F3A09771266}
AppName=SimpleBrain
AppVersion={#AppVersion}
AppPublisher=SimpleBrain
DefaultDirName={localappdata}\Programs\SimpleBrain
DefaultGroupName=SimpleBrain
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=SimpleBrain-{#AppVersion}-windows-setup
SetupIconFile=..\..\build\icon.ico
UninstallDisplayIcon={app}\SimpleBrain.exe
Compression=lzma2
SolidCompression=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; Flags: unchecked

[Files]
Source: "..\..\dist\SimpleBrain\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\SimpleBrain"; Filename: "{app}\SimpleBrain.exe"
Name: "{autodesktop}\SimpleBrain"; Filename: "{app}\SimpleBrain.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SimpleBrain.exe"; Description: "Launch SimpleBrain"; Flags: nowait postinstall skipifsilent

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
