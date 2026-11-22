; Установщик Dynamic Color Picker (Inno Setup 6). Версия передаётся: ISCC /DMyVer=2.1.0 installer.iss
#ifndef MyVer
  #define MyVer "0.0.0"
#endif

[Setup]
AppId={{8C1B2F5E-7A4D-4E8B-9F3A-5DC0C0101001}
AppName=Dynamic Color Picker
AppVersion={#MyVer}
AppVerName=Dynamic Color Picker {#MyVer}
AppPublisher=ankord-droid
AppPublisherURL=https://github.com/ankord-droid/DynamicColorPicker
DefaultDirName={localappdata}\Programs\DynamicColorPicker
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=DynamicColorPicker-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\DynamicColorPicker.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Запускать вместе с Windows"; GroupDescription: "Дополнительно:"

[Files]
Source: "dist\DynamicColorPicker.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Dynamic Color Picker"; Filename: "{app}\DynamicColorPicker.exe"
Name: "{autodesktop}\Dynamic Color Picker"; Filename: "{app}\DynamicColorPicker.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DynamicColorPicker"; ValueData: """{app}\DynamicColorPicker.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\DynamicColorPicker.exe"; Description: "{cm:LaunchProgram,Dynamic Color Picker}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\DynamicColorPicker.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /im DynamicColorPicker.exe /f"; Flags: runhidden; RunOnceId: "KillDCP"
