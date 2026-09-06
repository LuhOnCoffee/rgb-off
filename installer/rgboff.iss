; Inno Setup script for RGB Off.
; Built in CI:  iscc /DMyAppVersion=1.0.0 installer\rgboff.iss
; Expects PyInstaller output in dist\ at the repo root.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

#define MyAppName "RGB Off"
#define MyAppPublisher "Jia Liang Lu"
#define MyAppURL "https://github.com/LuhOnCoffee/rgb-off"
#define MyAppExeName "RGBOff.exe"

[Setup]
AppId={{9E2C7F41-6B3D-4A18-9E0B-2C4F1D7A55B2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\RGB Off
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=RGBOff-{#MyAppVersion}-Setup
SetupIconFile=..\assets\rgboff.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Reaching RAM and GPU lighting goes through the SMBus, which needs elevation.
PrivilegesRequired=admin
; RGB Off lives in the tray, and its window-close handler hides rather than
; quits - so Restart Manager's polite WM_CLOSE is ignored and an upgrade
; would stall on "unable to automatically close all applications". force
; lets Restart Manager terminate it instead.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\RGBOff.exe";  DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\rgboff-cli.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";        DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE";          DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Turn RGB off now"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--off"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; shellexec, not the default CreateProcess: the app is manifested
; requireAdministrator (PawnIO needs an elevated process for SMBus), and
; CreateProcess cannot elevate - it fails with error 740.
Filename: "{app}\{#MyAppExeName}"; Description: "Open {#MyAppName}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallRun]
; Leave no scheduled tasks behind pointing at a deleted executable.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""RGB Off at Logon"" /F"; Flags: runhidden; RunOnceId: "DelBlackoutTask"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""OpenRGB SDK Server"" /F"; Flags: runhidden; RunOnceId: "DelServerTask"
