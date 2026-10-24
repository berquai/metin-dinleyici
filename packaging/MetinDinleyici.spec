# -*- mode: python ; coding: utf-8 -*-
# Metin Dinleyici — PyInstaller derleme tarifi.
# Doğrudan çalıştırmayın; packaging\build.bat bunu hazırlıklarla birlikte çağırır.
#   pyinstaller --noconfirm --distpath <dist> --workpath <work> packaging/MetinDinleyici.spec
# Beklenen hazırlık: <kök>/.build/tesseract klasörü (tesseract.exe, DLL'ler, tessdata/{tur,eng,osd})
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
BUILD = os.path.join(ROOT, ".build")
ICON = os.path.join(ROOT, "metin_dinleyici.ico")
if not os.path.isfile(ICON):
    ICON = os.path.join(SPECPATH, "metin_dinleyici.ico")
TESS = os.environ.get("MD_TESSERACT_DIR") or os.path.join(BUILD, "tesseract")
WINDOWS = sys.platform == "win32"

datas = [
    (ICON, "."),
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "NOTICE"), "."),
    (os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), "."),
]
if os.path.isdir(TESS):
    # 'datas' olarak eklenir: PyInstaller dokunmadan olduğu gibi kopyalar; tesseract.exe yanındaki
    # DLL'leri kendi klasöründe bulur.
    datas.append((TESS, "tesseract"))
else:
    print(f"UYARI: {TESS} yok; paket Tesseract OLMADAN derlenecek.")

datas += collect_data_files("docx")       # Word dışa aktarmanın varsayılan şablonu
datas += collect_data_files("certifi")    # çevrimiçi sesler için TLS sertifikaları

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=["edge_tts", "ebooklib.epub", "bs4", "docx",
                   "PySide6.QtMultimedia", "metindinleyici.selftest"],
    excludes=[
        # Kullanılmayan büyük modüller (paketi yüzlerce MB şişirir)
        "tkinter", "matplotlib", "numpy", "pandas", "scipy", "IPython",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick3D", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtDesigner",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest",
        "pymupdf4llm", "pymupdf_layout", "cv2", "onnxruntime", "sympy", "torch",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # klasör (onedir) paketi: hızlı açılır, virüs programlarına daha az takılır
    name="MetinDinleyici",
    console=False,                  # komut penceresi açılmaz
    icon=ICON,
    version=os.path.join(ROOT, "version_info.txt") if WINDOWS else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MetinDinleyici", upx=False)
