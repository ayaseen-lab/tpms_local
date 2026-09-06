#define MyAppName "TPMS Suite"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "Xynovix"
#define MyAppExeName "TPMS_Suite.exe"

[Setup]
AppId={{A7C4E2B1-9F31-4D8A-8C2E-7B6A5C4D3E21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppPublisher}\{#MyAppName}
DefaultGroupName={#MyAppPublisher}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist_installer
OutputBaseFilename=TPMS_Suite_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=tpms_suite.ico
InfoBeforeFile=whats_new.txt
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=TPMS Suite Setup — comparative Board vs SDR reporting
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCopyright=Copyright (C) {#MyAppPublisher}
MinVersion=10.0
UsedUserAreasWarning=no
DisableWelcomePage=no
; Optional Authenticode signing (requires a code-signing certificate):
;   iscc /S"signtool=signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a $f" tpms_suite.iss

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\TPMS_Suite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
