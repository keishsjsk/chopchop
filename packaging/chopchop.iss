; Установщик Windows (Inno Setup 6): ISCC packaging\chopchop.iss
; Версия берётся из переменной среды CHOPCHOP_VERSION (по умолчанию 0.2.0).

#define AppName "CHOPCHOP"
#define AppExe "CHOPCHOP.exe"
#ifndef AppVersion
  #define AppVersion GetEnv("CHOPCHOP_VERSION")
#endif
#if AppVersion == ""
  #undef AppVersion
  #define AppVersion "0.2.0"
#endif

[Setup]
; Постоянный идентификатор: по нему обновление ставится поверх прежней версии
AppId={{6C3D7A52-0B6F-4E57-9B1A-5D0E8C1F4A21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=CHOPCHOP
AppPublisherURL=https://github.com/keishsjsk/chopchop
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\resources\icons\chopchop.ico
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=CHOPCHOP-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Без прав администратора: установка в профиль пользователя, но можно выбрать «для всех»
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\CHOPCHOP\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
#include "file_associations.iss"
