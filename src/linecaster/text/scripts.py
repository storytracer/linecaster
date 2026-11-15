"""What a text says about its writing system: its dominant script (Unicode's Script property) and its direction (the
Unicode bidirectional algorithm's paragraph level). Inference only: the data model records a script or a direction
only where a source or a step says so; these functions answer for a text when asked.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from functools import lru_cache

import regex

#: Unicode's Script property values as ISO 15924 codes (Unicode 16, through the ``regex`` package), without
#: Common (``Zyyy``), Inherited (``Zinh``) and Unknown (``Zzzz``)
SCRIPT_CODES = tuple("""
Adlm Aghb Ahom Arab Armi Armn Avst Bali Bamu Bass Batk Beng Berf Bhks Bopo Brah Brai Bugi Buhd Cakm Cans Cari Cham Cher
Chrs Copt Cpmn Cprt Cyrl Deva Diak Dogr Dsrt Dupl Egyp Elba Elym Ethi Gara Geor Glag Gong Gonm Goth Gran Grek Gujr Gukh
Guru Hang Hani Hano Hatr Hebr Hira Hluw Hmng Hmnp Hung Ital Java Jurc Kali Kana Kawi Khar Khmr Khoj Kits Knda Krai Kthi
Lana Laoo Latn Lepc Limb Lina Linb Lisu Lyci Lydi Mahj Maka Mand Mani Marc Medf Mend Merc Mero Miao Mlym Modi Mong Mroo
Mtei Mult Mymr Nagm Nand Narb Nbat Newa Nkoo Nshu Ogam Olck Onao Orkh Orya Osge Osma Ougr Palm Pauc Pcun Perm Phag Phli
Phlp Phnx Plrd Prti Rjng Rohg Runr Samr Sarb Saur Seal Sgnw Shaw Shrd Sidd Sidt Sind Sinh Sogd Sogo Sora Soyo Sund Sunu
Sylo Syrc Tagb Takr Tale Talu Taml Tang Tavt Tayo Telu Tfng Tglg Thaa Thai Tibt Tirh Tnsa Todr Tols Toto Tutg Ugar Vaii
Vith Wara Wcho Xpeo Xsux Yezi Yiii Zanb""".split())
#: scripts written right to left (horizontal-rl by default)
RIGHT_TO_LEFT = frozenset({"Adlm", "Arab", "Armi", "Avst", "Chrs", "Cprt", "Elym", "Hatr", "Hebr", "Hung", "Khar",
                           "Lydi", "Mand", "Mani", "Mend", "Merc", "Mero", "Narb", "Nbat", "Nkoo", "Ougr", "Orkh",
                           "Palm", "Phli", "Phlp", "Phnx", "Prti", "Rohg", "Samr", "Sarb", "Sogd", "Sogo", "Syrc",
                           "Thaa", "Yezi"})
# the most frequent scripts first, so that a character's script is found after few tests
_FIRST = ("Latn", "Cyrl", "Grek", "Arab", "Hebr", "Hani", "Hira", "Kana", "Hang", "Deva", "Thai", "Beng", "Taml",
          "Geor", "Armn", "Ethi", "Mong", "Tibt", "Syrc", "Thaa")
_ORDER = _FIRST + tuple(c for c in SCRIPT_CODES if c not in _FIRST)
_PATTERNS = {c: regex.compile(rf"\p{{Script={c}}}") for c in _ORDER}
_ISOLATES = {"⁦": 1, "⁧": 1, "⁨": 1, "⁩": -1}           # LRI, RLI, FSI open; PDI closes


@lru_cache(maxsize=65536)
def script_of(ch: str) -> str | None:
    """The script of one character (an ISO 15924 code), ``None`` for Common, Inherited and unassigned ones."""
    for code in _ORDER:
        if _PATTERNS[code].match(ch):
            return code
    return None


def scripts(text: str) -> Counter:
    """The scripts of a text's characters, counted (Common and Inherited characters left out)."""
    return Counter(s for s in map(script_of, text) if s is not None)


def dominant_script(text: str) -> str | None:
    """The script most of a text's letters are in; ISO 15924's combinations where a text mixes them as its writing
    system does: ``Jpan`` (Han with Hiragana or Katakana), ``Kore`` (Hangul with Han). ``None`` for a text without
    letters of any script."""
    counts = scripts(text)
    if not counts:
        return None
    if counts.get("Hani") and (counts.get("Hira") or counts.get("Kana")) or (
            counts.get("Hira") and counts.get("Kana")):
        return "Jpan"
    if counts.get("Hang") and counts.get("Hani"):
        return "Kore"
    return counts.most_common(1)[0][0]


def first_strong_direction(text: str) -> str | None:
    """The paragraph direction of the Unicode bidirectional algorithm (UAX #9, P2 and P3): ``ltr`` or ``rtl`` by the
    first character of a strong class (L, or R and AL) outside isolates (LRI, RLI, FSI ... PDI), ``None`` where there
    is none."""
    depth = 0
    for ch in text:
        if ch in _ISOLATES:
            depth = max(depth + _ISOLATES[ch], 0)
            continue
        if depth:
            continue
        bidi = unicodedata.bidirectional(ch)
        if bidi == "L":
            return "ltr"
        if bidi in ("R", "AL"):
            return "rtl"
    return None


def default_direction(script: str | None) -> str:
    """The direction a script is usually written in horizontally: ``horizontal-rl`` for the right-to-left scripts,
    ``vertical-lr`` for Mongolian, else ``horizontal-lr``. Chinese, Japanese and Korean are written both ways: only a
    source or a step can say they are vertical."""
    if script in RIGHT_TO_LEFT:
        return "horizontal-rl"
    if script == "Mong":
        return "vertical-lr"
    return "horizontal-lr"
