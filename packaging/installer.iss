; Metin Dinleyici — Inno Setup kurulum betiği
; build.ps1 bunu kendiliğinden derler:  ISCC /DAppVersion=4.7 /DRoot=<proje kökü> installer.iss
; Yönetici izni İSTEMEZ: varsayılan olarak yalnızca o kullanıcıya kurulur (kurum bilgisayarlarında
; da çalışır). Kurulum sırasında "tüm kullanıcılar için" seçilirse yönetici izni sorulur.

#ifndef AppVersion
  #define AppVersion "0.0"
#endif
#ifndef Root
  #define Root ".."
#endif
#define AppName "Metin Dinleyici"
#define AppExe "MetinDinleyici.exe"
#if FileExists(Root + "\metin_dinleyici.ico")
  #define AppIcon Root + "\metin_dinleyici.ico"
#else
  #define AppIcon Root + "\packaging\metin_dinleyici.ico"
#endif

[Setup]
AppId={{8882A59A-94B2-452C-BD1F-2EF0026E95F5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Berkay Çelik
AppPublisherURL=https://github.com/berquai/metin-dinleyici
AppSupportURL=mailto:berkcel@gmail.com
AppCopyright=Copyright (C) 2026 Berkay Çelik — AGPL-3.0-or-later
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription={#AppName} Kurulumu
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Root}\dist
OutputBaseFilename=MetinDinleyici_{#AppVersion}_Kurulum
SetupIconFile={#AppIcon}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
InfoBeforeFile={#Root}\packaging\kurulum_bilgi.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ChangesAssociations=yes

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstüne kısayol oluştur"; GroupDescription: "Kısayollar:"
Name: "openwith"; Description: "PDF, EPUB, DOCX ve TXT dosyalarının sağ tık › Birlikte aç menüsüne ekle"; GroupDescription: "Dosyalar:"

[Files]
Source: "{#Root}\dist\MetinDinleyici\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Güncellemede eski sürümün kalıntıları yeni sürüme karışmasın
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\MetinDinleyici.Belge"; ValueType: string; ValueData: "Metin Dinleyici belgesi"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\MetinDinleyici.Belge\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},0"; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\MetinDinleyici.Belge\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "MetinDinleyici.Belge"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.epub\OpenWithProgids"; ValueType: string; ValueName: "MetinDinleyici.Belge"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.docx\OpenWithProgids"; ValueType: string; ValueName: "MetinDinleyici.Belge"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.txt\OpenWithProgids"; ValueType: string; ValueName: "MetinDinleyici.Belge"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith

[Run]
Filename: "{app}\{#AppExe}"; Description: "Metin Dinleyici'yi şimdi başlat"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    if MsgBox('Program kaldırıldı.' + #13#10#13#10 +
              'Kütüphaneniz, kaldığınız yerler, alıntılarınız, notlarınız, telaffuz sözlüğünüz ve ' +
              'ayarlarınız da silinsin mi?' + #13#10#13#10 +
              'Programı yeniden kuracaksanız "Hayır" deyin; her şey kaldığı gibi geri gelir. ' +
              '(Belge dosyalarınız her iki durumda da silinmez.)',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\MetinDinleyici'), True, True, True);
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\MetinDinleyici');
    end;
end;
