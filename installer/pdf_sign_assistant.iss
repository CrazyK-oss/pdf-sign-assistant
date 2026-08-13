; ============================================================
;  PDF Sign Assistant — script de Inno Setup
; ============================================================
;  Genera el Setup.exe que se publica en GitHub Releases.
;
;  Compilar:
;      iscc installer\pdf_sign_assistant.iss /DAppVersion=0.7.0
;
;  (el workflow de GitHub Actions pasa la versión desde
;   modules/version.py, así que el número no se duplica a mano)
;
;  Decisiones de diseño
;  --------------------
;  * PrivilegesRequired=lowest → instala en %LOCALAPPDATA%\Programs y
;    NO muestra el cartel de UAC. Para una app que no toca nada del
;    sistema, pedir permisos de administrador es fricción pura: mucha
;    gente abandona ahí. Es el mismo criterio que usa VS Code en su
;    instalador "User".
;  * La app escribe sus datos en %LOCALAPPDATA%\PDF Sign Assistant y
;    los documentos firmados en Documentos\PDF Sign Assistant, así que
;    la carpeta de instalación puede ser de sólo lectura sin problema.
;  * La desinstalación NO borra los documentos firmados. Son del
;    usuario; borrarlos sería una sorpresa muy desagradable.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName        "PDF Sign Assistant"
#define AppPublisher   "CrazyK-oss"
#define AppURL         "https://github.com/CrazyK-oss/pdf-sign-assistant"
#define AppExeName     "PDF Sign Assistant.exe"
#define SourceDir      "..\dist\PDF Sign Assistant"

[Setup]
AppId={{8F3A6C21-4D7B-4E9A-9C15-2B8E7A0D3F64}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}

; Sin UAC: instala en la carpeta del usuario
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

OutputDir=..\dist\installer
OutputBaseFilename=PDFSignAssistant-{#AppVersion}-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

LicenseFile=..\LICENSE

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Todo el contenido de la carpeta que genera PyInstaller
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Sólo lo que genera la propia instalación. Los documentos firmados y
; la configuración del usuario NO se tocan.
Type: filesandordirs; Name: "{app}\_internal"

[Messages]
spanish.WelcomeLabel2=Esto instalará [name/ver] en tu equipo.%n%nLos documentos que firmes se guardarán en tu carpeta Documentos, y no se borran al desinstalar.
