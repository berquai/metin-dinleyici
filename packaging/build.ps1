# Metin Dinleyici — Windows paketleme betiği
# Kullanım: packaging\build.bat dosyasına çift tıklayın (bu betiği doğru izinlerle çağırır).
#
# Yaptıkları:
#   1. Python sanal ortamı kurar, gerekli paketleri ve PyInstaller'ı yükler (yalnızca .build içine).
#   2. Bilgisayardaki Tesseract OCR'ı bulur (yoksa winget ile kurmayı dener), Türkçe ve İngilizce dil
#      verisiyle birlikte .build\tesseract klasörüne kopyalar; Türkçe veri eksikse indirir.
#   3. PyInstaller ile dist\MetinDinleyici klasörünü oluşturur.
#   4. Paketlenmiş programın öz-sınamasını çalıştırır (OCR dahil). Hata varsa durur.
#   5. Inno Setup kuruluysa kurulum dosyası (Kurulum.exe), değilse taşınabilir zip üretir.
#
# Parametreler:
#   -Clean       Önceki derleme kalıntılarını silip baştan başlar.
#   -NoInstaller Kurulum dosyası üretmez, yalnızca klasör ve zip.

param([switch]$Clean, [switch]$NoInstaller)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest'i çok hızlandırır
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root  = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root ".build"
$Dist  = Join-Path $Root "dist"
$Venv  = Join-Path $Build "venv"
$Py    = Join-Path $Venv "Scripts\python.exe"

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "HATA: $msg" -ForegroundColor Red; exit 1 }

$init = Get-Content (Join-Path $Root "metindinleyici\__init__.py") -Raw -Encoding UTF8
if ($init -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') { Fail "Sürüm numarası okunamadı." }
$Version = $Matches[1]
Write-Host "Metin Dinleyici $Version paketleniyor" -ForegroundColor Green

if ($Clean) {
    Step "Eski derleme kalıntıları siliniyor"
    foreach ($d in @((Join-Path $Build "work"), (Join-Path $Build "tesseract"), $Dist)) {
        if (Test-Path $d) { Remove-Item $d -Recurse -Force }
    }
}
New-Item -ItemType Directory -Force -Path $Build, $Dist | Out-Null

# ── 1. Python ──────────────────────────────────────────────────────────────
Step "Python ortamı hazırlanıyor"
if (-not (Test-Path $Py)) {
    $base = $null
    $cands = @(@{ Exe = "py"; Args = @("-3") }, @{ Exe = "python"; Args = @() })
    foreach ($c in $cands) {
        try {
            $v = & $c.Exe $c.Args -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -and [version]$v -ge [version]"3.10") { $base = $c; break }
        } catch {}
    }
    if (-not $base) { Fail "Python 3.10 veya üstü bulunamadı. python.org'dan kurun (Add to PATH işaretli)." }
    & $base.Exe $base.Args -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail "Sanal ortam kurulamadı." }
}
& $Py -m pip install --upgrade pip --quiet --disable-pip-version-check
& $Py -m pip install -r (Join-Path $Root "requirements.txt") "pyinstaller>=6.3" --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "Paketler yüklenemedi (internet bağlantısını denetleyin)." }

# ── 2. Tesseract ───────────────────────────────────────────────────────────
Step "Tesseract OCR hazırlanıyor"
function Find-Tesseract {
    $c = @(
        $env:TESSERACT_CMD,
        "$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
        "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe",
        "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe"
    )
    foreach ($p in $c) { if ($p -and (Test-Path $p)) { return $p } }
    $w = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    if ($w) { return $w.Source }
    return $null
}
$tess = Find-Tesseract
if (-not $tess) {
    Write-Host "Tesseract bulunamadı; winget ile kuruluyor (UB Mannheim sürümü)..."
    try {
        winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements --silent
    } catch {}
    $tess = Find-Tesseract
}
if (-not $tess) {
    Fail ("Tesseract kurulamadı. https://github.com/UB-Mannheim/tesseract/wiki adresinden kurup " +
          "betiği yeniden çalıştırın.")
}
$TessSrc = Split-Path -Parent $tess
Write-Host "Kaynak: $TessSrc"

$TessDst = Join-Path $Build "tesseract"
if (Test-Path $TessDst) { Remove-Item $TessDst -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $TessDst "tessdata") | Out-Null
Copy-Item (Join-Path $TessSrc "tesseract.exe") $TessDst
Get-ChildItem $TessSrc -Filter *.dll | Copy-Item -Destination $TessDst
foreach ($f in @("LICENSE", "LICENSE.txt", "COPYING", "AUTHORS")) {
    $p = Join-Path $TessSrc $f
    if (Test-Path $p) { Copy-Item $p $TessDst }
}
$srcData = Join-Path $TessSrc "tessdata"
foreach ($lang in @("tur", "eng", "osd")) {
    $dst = Join-Path $TessDst "tessdata\$lang.traineddata"
    $src = Join-Path $srcData "$lang.traineddata"
    if (Test-Path $src) {
        Copy-Item $src $dst
    } else {
        Write-Host "$lang dil verisi bilgisayarda yok, indiriliyor..."
        $url = "https://github.com/tesseract-ocr/tessdata/raw/main/$lang.traineddata"
        try { Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing }
        catch { Fail "$lang.traineddata indirilemedi: $url" }
    }
}
$sizeMB = [math]::Round(((Get-ChildItem $TessDst -Recurse | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "Tesseract paketi hazır ($sizeMB MB)."

# ── 3. PyInstaller ─────────────────────────────────────────────────────────
Step "Program derleniyor (birkaç dakika sürebilir)"
$AppDir = Join-Path $Dist "MetinDinleyici"
if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
$env:MD_TESSERACT_DIR = $TessDst
& $Py -m PyInstaller --noconfirm --log-level WARN `
    --distpath $Dist --workpath (Join-Path $Build "work") `
    (Join-Path $PSScriptRoot "MetinDinleyici.spec")
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller derlemesi başarısız oldu." }

# AGPL: programı verdiğiniz herkese kaynak kodu da verilir.
$SrcDir = Join-Path $AppDir "kaynak_kod"
New-Item -ItemType Directory -Force -Path $SrcDir | Out-Null
$stage = Join-Path $Build "kaynak"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
foreach ($item in @("main.py", "metindinleyici", "packaging", "LICENSE", "NOTICE",
                    "THIRD_PARTY_NOTICES.md", "README.md", "requirements.txt", "version_info.txt")) {
    $p = Join-Path $Root $item
    if (Test-Path $p) { Copy-Item $p $stage -Recurse }
}
Get-ChildItem $stage -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath (Join-Path $SrcDir "MetinDinleyici_${Version}_kaynak.zip") -Force

# ── 4. Öz-sınama ───────────────────────────────────────────────────────────
Step "Paketlenmiş program sınanıyor"
$report = Join-Path $Build "oz_sinama.txt"
if (Test-Path $report) { Remove-Item $report }
$p = Start-Process -FilePath (Join-Path $AppDir "MetinDinleyici.exe") `
        -ArgumentList @("--self-test", "`"$report`"") -Wait -PassThru
if (-not (Test-Path $report)) { Fail "Öz-sınama rapor üretmedi; program açılamıyor olabilir." }
Get-Content $report -Encoding UTF8 | ForEach-Object {
    if ($_ -like "*[HATA]*") { Write-Host $_ -ForegroundColor Red } else { Write-Host $_ }
}
if ($p.ExitCode -ne 0) { Fail "Öz-sınama başarısız. Ayrıntı: $report" }
if ((Get-Content $report -Raw -Encoding UTF8) -notmatch "paketin içindeki Tesseract") {
    Fail "OCR paketin içindeki Tesseract'ı kullanmıyor; başka bilgisayarda çalışmaz."
}

# ── 5. Kurulum dosyası / zip ───────────────────────────────────────────────
$zip = Join-Path $Dist "MetinDinleyici_${Version}_tasinabilir.zip"
Step "Taşınabilir zip hazırlanıyor"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $AppDir -DestinationPath $zip

if (-not $NoInstaller) {
    Step "Kurulum dosyası hazırlanıyor"
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) {
        Write-Host "Inno Setup bulunamadı; winget ile kuruluyor..."
        try {
            winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements --silent
        } catch {}
        $iscc = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if ($iscc) {
        & $iscc /Q "/DAppVersion=$Version" "/DRoot=$Root" (Join-Path $PSScriptRoot "installer.iss")
        if ($LASTEXITCODE -ne 0) { Fail "Kurulum dosyası derlenemedi." }
    } else {
        Write-Host "Inno Setup kurulamadı; yalnızca taşınabilir zip üretildi." -ForegroundColor Yellow
    }
}

$total = [math]::Round(((Get-ChildItem $AppDir -Recurse | Measure-Object Length -Sum).Sum / 1MB), 0)
Write-Host ""
Write-Host "BİTTİ. Program klasörü: $AppDir ($total MB)" -ForegroundColor Green
Get-ChildItem $Dist -File | ForEach-Object {
    Write-Host ("  {0}  ({1} MB)" -f $_.Name, [math]::Round($_.Length / 1MB, 0)) -ForegroundColor Green
}
Start-Process explorer.exe $Dist
