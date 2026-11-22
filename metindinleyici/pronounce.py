# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Telaffuz sözlüğü.

Kurallar yalnızca sese gönderilen metni değiştirir; ekranda görünen metin olduğu gibi kalır.
Kurallar sırayla uygulanır: üstteki kural önce çalışır ve sonrakiler onun çıktısını görür.
Böylece "ss. 12-15" gibi özel bir kalıbı genel "s. 12" kuralından önce yakalamak mümkündür.

İki kural türü vardır:
- Kelime: yazılan ifade metinde ayrı bir kelime olarak geçtiğinde değiştirilir
  ("AB", "ABD"nin içinde eşleşmez). Okunuş olduğu gibi kullanılır.
- Düzenli ifade: bağlama bağlı kalıplar için. Okunuşta şu yer tutucular kullanılabilir:
    {1}          1. parantez grubunun kendisi
    {yazıyla:1}  1. gruptaki sayıyı yazıyla (125 → yüz yirmi beş)
    {sıra:1}     1. gruptaki sayıyı sıra sayısı olarak (19 → on dokuzuncu)
    {roma:1}     1. gruptaki Roma rakamını yazıyla (XIX → on dokuz)
    {romasıra:1} 1. gruptaki Roma rakamını sıra sayısı olarak (II → ikinci)

İstisnalar: her satır bir ifadedir. Eşleşmenin çevresindeki ±40 karakterde bu ifadelerden
biri geçiyorsa (büyük/küçük harf ayrımı yapılmadan) kural o yerde uygulanmaz.
"""
import re
import unicodedata
from dataclasses import dataclass, field

KIND_WORD = "word"
KIND_REGEX = "regex"
EXCEPTION_WINDOW = 40

# ───────────────────────────── Türkçe sayılar ─────────────────────────────

_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SCALES = ["", "bin", "milyon", "milyar", "trilyon", "katrilyon"]


def _three(n):
    h, rest = divmod(n, 100)
    t, o = divmod(rest, 10)
    parts = []
    if h:
        parts.append("yüz" if h == 1 else f"{_ONES[h]} yüz")
    if t:
        parts.append(_TENS[t])
    if o:
        parts.append(_ONES[o])
    return " ".join(parts)


def number_to_words(n):
    """Tam sayıyı Türkçe yazıya çevirir: 1923 → bin dokuz yüz yirmi üç."""
    n = orig = int(n)
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + number_to_words(-n)
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    if len(groups) > len(_SCALES):
        return str(orig)
    words = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if not g:
            continue
        if i == 1 and g == 1:
            words.append("bin")                  # "bir bin" değil, "bin"
        else:
            words.append(_three(g) + (f" {_SCALES[i]}" if i else ""))
    return " ".join(words)


_VOWELS = "aeıioöuü"
_HARMONY = {"a": "ı", "ı": "ı", "e": "i", "i": "i", "o": "u", "u": "u", "ö": "ü", "ü": "ü"}


def ordinal_words(n):
    """Sıra sayısı: 1 → birinci, 4 → dördüncü, 19 → on dokuzuncu, 1000 → bininci."""
    words = number_to_words(n)
    head, _, last = words.rpartition(" ")
    if last == "dört":
        last = "dörd"                          # ünsüz yumuşaması: dört → dördüncü
    v = next((c for c in reversed(last) if c in _VOWELS), "i")
    h = _HARMONY[v]
    suffix = ("nc" if last[-1] in _VOWELS else f"{h}nc") + h
    return (head + " " if head else "") + last + suffix


_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(s):
    """XIX → 19. Geçersiz bir Roma rakamıysa None döndürür."""
    s = s.upper()
    if not s or any(c not in _ROMAN_VALUES for c in s):
        return None
    total = 0
    for i, c in enumerate(s):
        v = _ROMAN_VALUES[c]
        total += -v if i + 1 < len(s) and _ROMAN_VALUES[s[i + 1]] > v else v
    return total


# ───────────────────────────── Kurallar ─────────────────────────────

@dataclass
class Rule:
    pattern: str
    replacement: str
    kind: str = KIND_WORD
    case_sensitive: bool = False
    enabled: bool = True
    doc_id: str = None                # None: tüm belgeler
    exceptions: list = field(default_factory=list)
    note: str = ""
    id: int = None
    position: int = 0

    def to_dict(self):
        return {"pattern": self.pattern, "replacement": self.replacement, "kind": self.kind,
                "case_sensitive": self.case_sensitive, "enabled": self.enabled, "doc_id": self.doc_id,
                "exceptions": list(self.exceptions), "note": self.note}

    @classmethod
    def from_dict(cls, d):
        return cls(pattern=str(d.get("pattern", "")), replacement=str(d.get("replacement", "")),
                   kind=d.get("kind", KIND_WORD) if d.get("kind") in (KIND_WORD, KIND_REGEX) else KIND_WORD,
                   case_sensitive=bool(d.get("case_sensitive", False)), enabled=bool(d.get("enabled", True)),
                   doc_id=d.get("doc_id") or None,
                   exceptions=[str(x) for x in (d.get("exceptions") or []) if str(x).strip()],
                   note=str(d.get("note", "")))


def compile_rule(rule):
    """Kuralı derler. Dönüş: (derlenmiş ifade, hata iletisi)."""
    if not rule.pattern:
        return None, "Yazılış boş olamaz."
    flags = 0 if rule.case_sensitive else re.IGNORECASE
    if rule.kind == KIND_REGEX:
        try:
            return re.compile(rule.pattern, flags), None
        except re.error as e:
            return None, f"Düzenli ifade hatalı: {e}"
    # Kelime kuralı: ancak ifadenin kenarı harf/rakamsa, o kenarda başka harf/rakam olmamalı.
    p = re.escape(rule.pattern.strip())
    word = r"[^\W_]"
    if re.match(word, rule.pattern.strip()[0]):
        p = rf"(?<!{word})" + p
    if re.match(word, rule.pattern.strip()[-1]):
        p = p + rf"(?!{word})"
    return re.compile(p, flags), None


_PLACEHOLDER = re.compile(r"\{(?:(yazıyla|sıra|roma|romasıra):)?(\d+)\}")


def render(rule, m):
    if rule.kind != KIND_REGEX:
        return rule.replacement

    def sub(pm):
        fn, idx = pm.group(1), int(pm.group(2))
        try:
            val = m.group(idx) or ""
        except (IndexError, re.error):
            return pm.group(0)
        if fn in ("roma", "romasıra") and val:
            n = roman_to_int(val.strip())
            if n:
                return number_to_words(n) if fn == "roma" else ordinal_words(n)
            return val
        if fn and val:
            digits = re.sub(r"\D", "", val)
            if digits:
                return number_to_words(int(digits)) if fn == "yazıyla" else ordinal_words(int(digits))
        return val
    return _PLACEHOLDER.sub(sub, rule.replacement)


def _excepted(rule, text, m):
    if not rule.exceptions:
        return False
    a = max(0, m.start() - EXCEPTION_WINDOW)
    window = text[a:m.end() + EXCEPTION_WINDOW].casefold()
    return any(e.casefold() in window for e in rule.exceptions)


def apply_rule(rule, rx, text):
    """Tek bir kuralı uygular. Dönüş: (yeni metin, uygulanan yer sayısı)."""
    count = 0

    def repl(m):
        nonlocal count
        if _excepted(rule, text, m):
            return m.group(0)
        count += 1
        return render(rule, m)
    out = rx.sub(repl, text)
    return out, count


# ───────────────────────────── İnceltme işareti ─────────────────────────────
# Sinir ağı sesleri (özellikle çok dilli sesler) â, î, û harflerini Türkçe okumuyor: "edebî" → "edebiy",
# "kâr" → yabancı bir ünlü. Sese giden metinde bu harfler düz karşılıklarına çevrilir; ekrandaki metin değişmez.
# Kullanıcı kuralları önce çalışır: "hikâye" gibi bir kelimeye özel okunuş sözlükte yine tanımlanabilir.
SIMPLIFY_CIRCUMFLEX = True                # ana pencere ayara göre değiştirir (Düzen › Telaffuz menüsü)
_CIRCUMFLEX = str.maketrans({"â": "a", "Â": "A", "î": "i", "Î": "İ", "û": "u", "Û": "U",
                             "ˆ": "", "̂": ""})          # ayrı yazılmış şapka işaretleri de atılır


def simplify_circumflex(text):
    if not any(c in text for c in "âÂîÎûÛˆ̂"):
        return text
    return unicodedata.normalize("NFC", text).translate(_CIRCUMFLEX)


class Pronouncer:
    """Etkin kuralları sırayla uygular. Belgeye özel kurallar yalnızca o belgede çalışır."""

    def __init__(self, rules=(), doc_id=None, simplify=None):
        self.simplify = SIMPLIFY_CIRCUMFLEX if simplify is None else simplify
        self.compiled = []
        for r in rules:
            if not r.enabled or (r.doc_id and r.doc_id != doc_id):
                continue
            rx, err = compile_rule(r)
            if rx is not None:
                self.compiled.append((r, rx))

    def apply(self, text):
        if not self.compiled:
            return simplify_circumflex(text) if self.simplify else text
        out = text
        for r, rx in self.compiled:
            out, _ = apply_rule(r, rx, out)
        out = re.sub(r"\s{2,}", " ", out).strip() or text   # tüm cümle silindiyse aslını oku
        return simplify_circumflex(out) if self.simplify else out

    def trace(self, text):
        """Ön izleme için: her kuralın etkisini sırayla döndürür → (sonuç, [(kural, adet)])."""
        out, steps = text, []
        for r, rx in self.compiled:
            out, n = apply_rule(r, rx, out)
            if n:
                steps.append((r, n))
        out = re.sub(r"\s{2,}", " ", out).strip() or text
        return (simplify_circumflex(out) if self.simplify else out), steps

    def __bool__(self):
        return bool(self.compiled) or self.simplify


# Başlangıç kuralları: ilk açılışta bir kez eklenir; hepsi düzenlenebilir ve silinebilir.
STARTER_RULES = [
    Rule(r"\bss\.\s*(\d+)\s*[-–]\s*(\d+)", "sayfa {yazıyla:1} ile {yazıyla:2} arası", KIND_REGEX,
         note="Sayfa aralığı: ss. 12-15"),
    Rule(r"\b[sS]\.\s*(\d+)\s*[-–]\s*(\d+)", "sayfa {yazıyla:1} ile {yazıyla:2} arası", KIND_REGEX,
         case_sensitive=True, note="Sayfa aralığı: s. 12-15"),
    Rule(r"\b[sSpP]\.\s*(\d+)", "sayfa {yazıyla:1}", KIND_REGEX, case_sensitive=True,
         note="Sayfa atfı: s. 125 → sayfa yüz yirmi beş"),
    Rule(r"(\d+)\s*s(?=\.(?:[\s,;)]|$))", "{yazıyla:1} sayfa", KIND_REGEX, case_sensitive=True,
         note="Kaynakçada sayfa sayısı: 250 s. → iki yüz elli sayfa"),
    Rule(r"\b(\d{1,2})\.\s*(?:yüzyıl|yy\.?)", "{sıra:1} yüzyıl", KIND_REGEX,
         note="19. yy. → on dokuzuncu yüzyıl"),
    Rule(r"\b([IVXLC]{1,6})\.\s*(?:yüzyıl|yy\.?)", "{romasıra:1} yüzyıl", KIND_REGEX, case_sensitive=True,
         note="XIX. yüzyıl → on dokuzuncu yüzyıl"),
    Rule(r"\b([IVX]{1,4})\.\s+(?=[A-ZÇĞİÖŞÜ])", "{romasıra:1} ", KIND_REGEX, case_sensitive=True,
         note="II. Abdülhamid → ikinci Abdülhamid, I. Dünya Savaşı → birinci Dünya Savaşı"),
    Rule("bkz.", "bakınız", note="Kaynak göstermede"),
    Rule("krş.", "karşılaştırınız"),
    Rule("vb.", "ve benzeri"),
    Rule("vs.", "vesaire"),
    Rule("vd.", "ve diğerleri"),
    Rule("a.g.e.", "adı geçen eser"),
    Rule("a.g.m.", "adı geçen makale"),
    Rule("age.", "adı geçen eser"),
    Rule("çev.", "çeviren"),
    Rule("haz.", "hazırlayan"),
    Rule("TBMM", "Türkiye Büyük Millet Meclisi", case_sensitive=True),
    Rule("CHP", "Ce He Pe", case_sensitive=True),
]
