#define AppVersion "0.27.0-dev"
[Setup]
AppId={{A8AB7016-CAD6-4E34-88A6-41C1E465F737}
AppName=Agent Remote
AppVersion={#AppVersion}
VersionInfoVersion=0.27.0.0
DefaultDirName={localappdata}\Programs\AgentRemote
DefaultGroupName=Agent Remote
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=AgentRemote-0.27.0-dev-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
SetupIconFile=..\..\static\app.ico
UninstallDisplayIcon={app}\AgentRemote.exe
[Files]
Source: "..\..\dist\AgentRemote\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\.toolchain\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView
[Icons]
Name: "{group}\Agent Remote"; Filename: "{app}\AgentRemote.exe"
Name: "{autodesktop}\Agent Remote"; Filename: "{app}\AgentRemote.exe"
[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; Flags: waituntilterminated; Check: NeedsWebView
Filename: "{app}\AgentRemote.exe"; Description: "启动 Agent Remote"; Flags: nowait postinstall skipifsilent
[UninstallDelete]
Type: files; Name: "{userstartup}\Agent Remote 027.lnk"
[Code]
function NeedsWebView: Boolean;
var Version: String;
begin
  Result := not ((RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'))
    or (RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')));
end;
