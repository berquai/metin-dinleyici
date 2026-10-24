# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Seslendirme motorları: Windows SAPI (çevrimdışı) ve Microsoft Edge sinir ağı sesleri (çevrimiçi)."""
import asyncio
import bisect
import math
import os
import subprocess
import threading
import time
import wave

EDGE_VOICES = [
    ("Türkçe — Emel", "tr-TR-EmelNeural"),
    ("Türkçe — Ahmet (sunucuda kararsız)", "tr-TR-AhmetNeural"),
    ("Çok dilli — Brian (erkek)", "en-US-BrianMultilingualNeural"),
    ("Çok dilli — Andrew (erkek)", "en-US-AndrewMultilingualNeural"),
    ("Çok dilli — Florian (erkek)", "de-DE-FlorianMultilingualNeural"),
    ("Çok dilli — Emma (kadın)", "en-US-EmmaMultilingualNeural"),
    ("Çok dilli — Ava (kadın)", "en-US-AvaMultilingualNeural"),
    ("İngilizce (ABD) — Jenny", "en-US-JennyNeural"),
    ("İngilizce (ABD) — Guy", "en-US-GuyNeural"),
    ("İngilizce (İngiltere) — Sonia", "en-GB-SoniaNeural"),
    ("İngilizce (İngiltere) — Ryan", "en-GB-RyanNeural"),
    ("Almanca — Katja", "de-DE-KatjaNeural"),
    ("Fransızca — Denise", "fr-FR-DeniseNeural"),
]



_procs, _procs_lock = set(), threading.Lock()


def kill_all_processes():
    with _procs_lock:
        for p in list(_procs):
            try:
                p.kill()
            except Exception:
                pass


def run_powershell(script, env_extra, timeout):
    env = dict(os.environ)
    env.update(env_extra)
    p = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with _procs_lock:
        _procs.add(p)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        raise RuntimeError("Windows ses motoru zaman aşımına uğradı.")
    finally:
        with _procs_lock:
            _procs.discard(p)
    return p.returncode, out, err


# Metin, komut satırına gömülmez; ortam değişkeniyle aktarılır. Böylece Türkiye’nin gibi
# kesme işaretleri PowerShell betiğini bozamaz.
_PS_SPEAK = (
    "Add-Type -AssemblyName System.Speech; "
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "if($env:MD_VOICE){ try { $s.SelectVoice($env:MD_VOICE) } catch {} }; "
    "$s.Rate=[int]$env:MD_RATE; $s.SetOutputToWaveFile($env:MD_OUT); "
    "$s.Speak($env:MD_TEXT); $s.Dispose()"
)
_PS_VOICES = (
    "Add-Type -AssemblyName System.Speech; "
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.GetInstalledVoices() | Where-Object { $_.Enabled } | "
    "ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name }"
)


def sapi_rate(pct):
    # SAPI hızı -10..+10 arası logaritmik bir ölçektir; +10 ≈ 3 kat, -10 ≈ 1/3 hız.
    return max(-10, min(10, round(10 * math.log(pct / 100) / math.log(3))))


def synth_sapi(text, voice, rate_pct, out):
    code, _, err = run_powershell(_PS_SPEAK, {"MD_TEXT": text, "MD_VOICE": voice or "", "MD_OUT": out,
                                              "MD_RATE": str(sapi_rate(rate_pct))}, timeout=120)
    if code != 0 or not os.path.exists(out) or os.path.getsize(out) < 100:
        raise RuntimeError(f"Windows ses motoru ses üretemedi.\nAyrıntı: {err.strip()[:400]}")
    try:
        with wave.open(out, "rb") as w:
            return int(w.getnframes() / max(1, w.getframerate()) * 1000)
    except Exception:
        return None


def list_sapi_voices():
    code, out, _ = run_powershell(_PS_VOICES, {}, timeout=30)
    voices = []
    for line in out.splitlines():
        if "|" in line:
            name, culture = line.strip().split("|", 1)
            voices.append((name, culture))
    return voices


# ── Çevrimiçi (Edge) seslendirme: parça bazlı üretim + sessizlik kırpma ──
#
# Edge her isteğin sonuna ~1 sn, cümleler arasına da ~1 sn sessizlik koyar. Cümle cümle
# istemek bu sessizliği her cümlede tekrarlar. Bu yüzden sesi birkaç cümlelik parçalar
# hâlinde alıp, kelime zaman damgalarıyla hangi cümlenin nerede başladığını buluyor ve
# fazla sessizliği MP3 çerçevesi düzeyinde kesiyoruz (yeniden kodlama yok, kalite kaybı yok).

FRAME_BYTES, FRAME_SEC = 144, 0.024     # Edge: 24 kHz / 48 kbps / mono MP3 → çerçeve başına 144 bayt, 24 ms


def _edge_net_kwargs():
    """Kurum ağlarında vekil sunucu (proxy) ve özel sertifika desteği."""
    kw = {}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        kw["proxy"] = proxy
    ca = os.environ.get("SSL_CERT_FILE")
    if ca and os.path.isfile(ca):
        import ssl, aiohttp
        kw["connector"] = aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=ca))
    return kw


async def _edge_stream(text, voice, rate):
    import edge_tts
    audio, words = bytearray(), []
    try:
        comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary", **_edge_net_kwargs())
    except TypeError:                     # edge-tts 7'den eski sürümler: kelime sınırı zaten varsayılan
        comm = edge_tts.Communicate(text, voice, rate=rate)
    async for c in comm.stream():
        if c["type"] == "audio":
            audio += c["data"]
        elif c["type"] == "WordBoundary":
            words.append((c["offset"] / 1e7, c["duration"] / 1e7, c["text"]))
    return bytes(audio), words


def edge_synth_raw(text, voice, rate_pct, attempts=4):
    import importlib.util
    if importlib.util.find_spec("edge_tts") is None:
        raise RuntimeError("Çevrimiçi ses paketi eksik:\npy -m pip install --upgrade edge-tts")
    rate = f"{rate_pct - 100:+d}%"
    last = None
    for k in range(attempts):
        try:
            audio, words = asyncio.run(_edge_stream(text, voice, rate))
            if len(audio) > 200:
                return audio, words
            last = RuntimeError("Ses servisi boş yanıt döndürdü.")
        except Exception as e:
            last = e
        time.sleep(0.3 * (k + 1))
    if type(last).__name__ == "NoAudioReceived":
        raise RuntimeError(
            f"“{voice}” sesi Microsoft sunucusundan {attempts} denemede de ses döndürmedi.\n\n"
            "Bu ses sunucu tarafında kararsız çalışıyor; sorun programda değil. "
            "Emel'i ya da listedeki çok dilli erkek seslerinden birini (Brian, Andrew, Florian) deneyin.")
    raise RuntimeError("Çevrimiçi ses üretilemedi. İnternet bağlantısını kontrol edin; sorun sürerse:\n"
                       f"py -m pip install --upgrade edge-tts\n\nAyrıntı: {last}")


def align_sentences(texts, words):
    """Edge'in kelime zaman damgalarını bizim cümlelerimize eşler → her cümle için [başlangıç, bitiş] sn."""
    joined = " ".join(texts)
    starts, p = [], 0
    for t in texts:
        starts.append(p)
        p += len(t) + 1
    spans = [[None, None] for _ in texts]
    cur = 0
    for off, dur, w in words:
        w = w.strip()
        if not w:
            continue
        pos = joined.find(w, cur)
        if pos < 0 or pos - cur > 200:       # bulunamayan ya da çok uzakta eşleşen kelimeyi atla
            continue
        cur = pos + len(w)
        s = spans[bisect.bisect_right(starts, pos) - 1]
        if s[0] is None:
            s[0] = off
        s[1] = off + dur
    prev = 0.0
    for s in spans:                          # kelimesi eşleşmeyen cümleler: bir öncekinin sonuna yasla
        if s[0] is None:
            s[0] = s[1] = prev
        prev = s[1]
    return spans


def trim_silences(audio, spans, pause):
    """Cümle aralarındaki sessizliği `pause` saniyeye indirir; sondaki fazlalığı atar.
    Dönüş: (yeni ses baytları, her cümle için (başlangıç_ms, bitiş_ms))."""
    uniform = len(audio) % FRAME_BYTES == 0 and all(
        audio[i] == 0xFF and (audio[i + 1] & 0xE0) == 0xE0 for i in range(0, len(audio), FRAME_BYTES))
    if not uniform:          # beklenmeyen biçim: kesmeden olduğu gibi kullan
        return audio, [(int(a * 1000), int(b * 1000)) for a, b in spans]
    nframes = len(audio) // FRAME_BYTES
    cuts = []
    for (_, e), (s, _) in zip(spans, spans[1:]):
        if s - e > pause + 0.05:
            f1 = math.ceil((e + pause * 0.6) / FRAME_SEC)
            f2 = math.floor((s - pause * 0.4) / FRAME_SEC)
            if f2 > f1:
                cuts.append((f1, f2))
    tail = math.ceil((spans[-1][1] + max(0.2, pause * 0.6)) / FRAME_SEC)
    if tail < nframes:
        cuts.append((tail, nframes))
    out, pos = bytearray(), 0
    for f1, f2 in cuts:
        out += audio[pos * FRAME_BYTES:f1 * FRAME_BYTES]
        pos = f2
    out += audio[pos * FRAME_BYTES:]

    def remap(t):
        f, shift = t / FRAME_SEC, 0.0
        for f1, f2 in cuts:
            if f >= f2:
                shift += f2 - f1
            elif f > f1:
                shift += f - f1
        return (f - shift) * FRAME_SEC

    return bytes(out), [(int(remap(a) * 1000), int(remap(b) * 1000)) for a, b in spans]


def synth_edge_chunk(texts, voice, rate_pct, out, pause):
    audio, words = edge_synth_raw(" ".join(texts), voice, rate_pct)
    data, times = trim_silences(audio, align_sentences(texts, words), pause)
    with open(out, "wb") as f:
        f.write(data)
    return times


def safe_remove(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
