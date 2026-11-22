# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Kara kutu: hata günlüğü, oturum izi ve güvenli mod.

Paketlenmiş (konsolsuz) programda hatalar ekrana yazılamaz; program sessizce kapanırsa neden kapandığı
bilinmez. Bu modül her şeyi bir günlük dosyasına yazar:

- Python hataları (ana iş parçacığı ve arka plan iş parçacıkları),
- C/C++ katmanındaki çökmeler (PDF motoru, Qt, ses): faulthandler, çökme anında bütün iş parçacıklarının
  hangi Python satırında olduğunu yazar,
- Qt'nin uyarı ve ölümcül hata iletileri,
- açılışın aşamaları ve pencerenin ekrandaki konumu.

Oturum dosyası (oturum.json) programın bir önceki çalışmasının nasıl bittiğini tutar. Açılış sırasında iz
bırakmadan kesilmiş bir oturum, bir sonraki açılışta fark edilir ve güvenli mod önerilir. Hiç iz yoksa
program dışarıdan (ör. bir güvenlik yazılımı tarafından) sonlandırılmış olabilir; bu da günlükte görünür.
"""
import datetime
import faulthandler
import json
import os
import platform
import sys
import threading
import traceback

LOG_NAME = "metin_dinleyici.log"
SESSION_NAME = "oturum.json"
MAX_LOG_BYTES = 512 * 1024          # aşılınca eski günlük .1 uzantısıyla saklanır (bir kuşak)
MAX_QT_MESSAGES = 200               # aynı oturumda yazılacak en fazla Qt iletisi (günlük şişmesin)
RUNNING_AFTER_MS = 5000             # pencere açıldıktan bu kadar sonra açılış "başarılı" sayılır

SAFE_MODE = False                   # güvenli modda açıldıysa True (diğer modüller okur)
_log = None
_lock = threading.Lock()
_qt_count = 0
_session = {}
_dir = None


def log_dir():
    """Günlük klasörü. Bir kez hesaplanır: veri klasörünün yolu Qt'deki uygulama adına bağlıdır; ad
    değişirse (ör. QApplication kurulunca) açılışta ve kapanışta farklı klasörlere bakılmasın."""
    global _dir
    if _dir is None:
        from .paths import data_dir
        _dir = os.path.join(data_dir(), "gunluk")
    os.makedirs(_dir, exist_ok=True)
    return _dir


def log_path():
    return os.path.join(log_dir(), LOG_NAME)


def _session_path():
    return os.path.join(log_dir(), SESSION_NAME)


def write(msg, level="BİLGİ"):
    """Günlüğe zaman damgalı bir satır yazar. Asla hata fırlatmaz."""
    if _log is None:
        return
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    try:
        with _lock:
            _log.write(f"{stamp} [{level}] {msg}\n")
            _log.flush()
    except Exception:
        pass


def _write_exception(title, exc_type, exc, tb):
    write(title + "\n" + "".join(traceback.format_exception(exc_type, exc, tb)).rstrip(), "HATA")


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        return sys.__excepthook__(exc_type, exc, tb)
    _write_exception("Yakalanmamış hata (ana iş parçacığı):", exc_type, exc, tb)


def _thread_hook(args):
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread else "?"
    _write_exception(f"Yakalanmamış hata (arka plan iş parçacığı: {name}):", args.exc_type, args.exc_value,
                     args.exc_traceback)


def _qt_handler(mode, context, message):
    """Qt iletileri: uyarılar sınırlı sayıda, kritik ve ölümcül olanlar her zaman yazılır."""
    global _qt_count
    from PySide6.QtCore import QtMsgType
    if mode == QtMsgType.QtDebugMsg or mode == QtMsgType.QtInfoMsg:
        return
    level = {QtMsgType.QtWarningMsg: "QT-UYARI", QtMsgType.QtCriticalMsg: "QT-KRİTİK",
             QtMsgType.QtFatalMsg: "QT-ÖLÜMCÜL"}.get(mode, "QT")
    if mode == QtMsgType.QtWarningMsg:
        _qt_count += 1
        if _qt_count > MAX_QT_MESSAGES:
            return
    where = f" ({context.file}:{context.line})" if getattr(context, "file", None) else ""
    write(f"{message}{where}", level)


def _read_session():
    try:
        with open(_session_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_session(data):
    try:
        tmp = _session_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _session_path())
    except Exception:
        pass


def install(version):
    """Günlüğü açar, hata yakalayıcıları kurar, önceki oturumun nasıl bittiğini döndürür.

    Dönüş: {"previous": önceki oturum durumu ("closed" | "running" | "starting" | None),
            "startup_fails": art arda açılışta kesilen oturum sayısı}"""
    global _log, _session
    path = log_path()
    try:
        if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass
    # Dosya açık kalmalı: faulthandler çökme anında doğrudan bu dosyanın tanıtıcısına yazar.
    _log = open(path, "a", encoding="utf-8", buffering=1)
    faulthandler.enable(file=_log, all_threads=True)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook

    prev = _read_session()
    prev_state = prev.get("state")
    fails = int(prev.get("startup_fails", 0)) + 1 if prev_state == "starting" else 0
    _session = {"state": "starting", "pid": os.getpid(), "version": version,
                "started": datetime.datetime.now().isoformat(timespec="seconds"), "startup_fails": fails}
    _write_session(_session)

    write("=" * 70)
    if sys.platform == "win32":
        write("Not: 'Windows fatal exception' satırından sonra günlük sürüyorsa o kayıt zararsızdır (yakalanıp "
              "atlatılmış bir istisna). Gerçek çökmede o oturuma ait başka satır gelmez.")
    write(f"Açılış başladı · sürüm {version} · süreç {os.getpid()}")
    write(f"Sistem: {platform.platform()} · Python {platform.python_version()} · "
          f"{'paketlenmiş' if getattr(sys, 'frozen', False) else 'kaynak koddan'} · {sys.executable}")
    if prev_state == "starting":
        write(f"ÖNCEKİ OTURUM AÇILIŞ SIRASINDA KESİLMİŞ (art arda {fails}. kez). Yukarıdaki son satırlara bakın; "
              "çökme izi yoksa program dışarıdan sonlandırılmış olabilir.", "UYARI")
    elif prev_state == "running":
        write("Önceki oturum kullanım sırasında beklenmedik biçimde sona ermiş (temiz kapanış kaydı yok).", "UYARI")
    return {"previous": prev_state, "startup_fails": fails}


def install_qt():
    """QApplication kurulduktan sonra çağrılır: Qt iletilerini ve sürüm bilgisini günlüğe bağlar."""
    try:
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qInstallMessageHandler, qVersion
        qInstallMessageHandler(_qt_handler)
        write(f"Qt {qVersion()} · PySide6 {pyside_version}")
    except Exception as e:
        write(f"Qt ileti yakalayıcısı kurulamadı: {e}", "UYARI")


def describe_screens(app):
    try:
        parts = []
        for s in app.screens():
            g = s.availableGeometry()
            parts.append(f"{s.name()} {g.x()},{g.y()} {g.width()}x{g.height()} ölçek {s.devicePixelRatio():g}")
        return " | ".join(parts) or "ekran yok"
    except Exception as e:
        return f"ekran bilgisi alınamadı: {e}"


def describe_window(w):
    try:
        g = w.frameGeometry()
        on = any(s.availableGeometry().intersects(g) for s in w.screen().virtualSiblings()) if w.screen() else False
        st = w.windowState()
        flags = [n for n, f in (("küçültülmüş", 0x1), ("büyütülmüş", 0x2), ("tam ekran", 0x4))
                 if int(getattr(st, "value", st)) & f]
        return (f"görünür={w.isVisible()} durum={'+'.join(flags) or 'normal'} "
                f"çerçeve={g.x()},{g.y()} {g.width()}x{g.height()} ekranla kesişiyor={on}")
    except Exception as e:
        return f"pencere bilgisi alınamadı: {e}"


def watch_window(w):
    """Ana pencere gizlenir ya da kapanırsa bunu, kimin yaptığıyla (Python çağrı yığını) birlikte yazar:
    pencere çökme olmadan kaybolursa sebebi buradan görünür."""
    from PySide6.QtCore import QEvent, QObject

    class _Watch(QObject):
        def eventFilter(self, obj, ev):
            t = ev.type()
            if t in (QEvent.Hide, QEvent.Close):
                what = "gizlendi" if t == QEvent.Hide else "kapatılıyor"
                stack = "".join(traceback.format_stack(limit=8)[:-1]).rstrip()
                write(f"Ana pencere {what} · {describe_window(obj)}\n{stack}")
            return False

    w._crashlog_watch = _Watch(w)
    w.installEventFilter(w._crashlog_watch)


def mark(state):
    """Oturum durumunu günceller: 'running' (açılış başarılı) ya da 'closed' (temiz kapanış)."""
    if not _session:
        return
    _session["state"] = state
    if state in ("running", "closed"):
        _session["startup_fails"] = 0
    _write_session(_session)
    write({"running": "Açılış başarılı.", "closed": "Program temiz biçimde kapandı."}.get(state, f"Durum: {state}"))


def stage(msg):
    """Açılış aşaması: çökme olursa günlükteki son aşama, nerede kesildiğini gösterir."""
    write(f"aşama: {msg}")
