; Inno Setup script for Comitra (per-user install, no administrator rights).
; Normally invoked by packaging/build.py, which passes the defines below.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\Comitra"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist\release"
#endif
#ifndef OutputName
  #define OutputName "Comitra-setup"
#endif
#ifndef IconFile
  #define IconFile "..\build-icons\comitra.ico"
#endif

[Setup]
AppId={{6C1F7E0B-2B5D-4E8A-9C1D-2A7C3B9E4F10}
AppName=Comitra
AppVersion={#AppVersion}
AppVerName=Comitra {#AppVersion}
AppPublisher=Comitra
DefaultDirName={autopf}\Comitra
DefaultGroupName=Comitra
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Comitra.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add comitra-cli to PATH"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Comitra"; Filename: "{app}\Comitra.exe"
Name: "{autodesktop}\Comitra"; Filename: "{app}\Comitra.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\Comitra.exe"; Description: "{cm:LaunchProgram,Comitra}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;
