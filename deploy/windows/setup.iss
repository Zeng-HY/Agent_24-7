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
; One step: a progress bar, then the app's own window (sign in, bind) takes over
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
ShowLanguageDialog=no
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
Filename: "{app}\AgentRemote.exe"; Flags: nowait skipifsilent
[Messages]
SetupAppTitle=安装
SetupWindowTitle=安装 %1
UninstallAppTitle=卸载
UninstallAppFullTitle=卸载 %1
ButtonBack=上一步
ButtonNext=下一步
ButtonInstall=安装
ButtonOK=确定
ButtonCancel=取消
ButtonYes=是
ButtonNo=否
ButtonFinish=完成
ExitSetupTitle=退出安装
ExitSetupMessage=还没装完，确定退出？
WizardPreparing=正在准备
PreparingDesc=
ApplicationsFound=这些程序正在使用要更新的文件：
ApplicationsFound2=这些程序正在使用要更新的文件，装完后会重新打开。
CloseApplications=自动关闭(&A)
DontCloseApplications=不关闭(&D)
WizardInstalling=正在安装
InstallingLabel=
StatusClosingApplications=正在关闭程序…
StatusCreateDirs=正在创建文件夹…
StatusExtractFiles=正在复制文件…
StatusCreateIcons=正在创建快捷方式…
StatusCreateRegistryEntries=正在写入设置…
StatusSavingUninstall=正在保存卸载信息…
StatusRunProgram=即将完成…
StatusRestartingApplications=正在重新打开程序…
StatusRollback=正在撤销…
ConfirmUninstall=卸载 %1？
UninstallStatusLabel=正在卸载 %1…
UninstalledAll=%1 已卸载。
[UninstallDelete]
Type: files; Name: "{userstartup}\Agent Remote 027.lnk"
[Code]
function NeedsWebView: Boolean;
var Version: String;
begin
  Result := not ((RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'))
    or (RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')));
end;
