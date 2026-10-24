# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Uyku modunu engelleme.

Windows'ta SetThreadExecutionState ile işletim sistemine "şu an kullanılıyorum" deriz:
- ES_SYSTEM_REQUIRED: bilgisayar uyku moduna geçmez (sesli okuma yarıda kesilmez),
- ES_DISPLAY_REQUIRED: ekran da kararmaz (tam ekranda gözle takip ederken).
ES_CONTINUOUS ile verilen istek, yenisi verilene kadar geçerli kalır. Program kapanınca
Windows isteği zaten kendiliğinden düşürür. Diğer işletim sistemlerinde hiçbir şey yapmaz.
"""
from .paths import IS_WINDOWS

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002

_current = None


def set_awake(system=False, display=False):
    """İstenen durumu uygular; aynı durum tekrar istenirse çağrıyı atlar."""
    global _current
    state = (bool(system or display), bool(display))
    if state == _current:
        return
    _current = state
    if not IS_WINDOWS:
        return
    flags = _ES_CONTINUOUS
    if state[0]:
        flags |= _ES_SYSTEM_REQUIRED
    if state[1]:
        flags |= _ES_DISPLAY_REQUIRED
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass
