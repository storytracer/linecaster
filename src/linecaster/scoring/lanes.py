"""Lanes: versioned normalizations a rendered text goes through before it is counted, the same for both sides of a
comparison. A lane is named ``<id>@<edition>``; a released edition never changes (a change is a new edition).

* ``diplomatic@1``: NFC; whitespace runs to one space; trimmed. Case, punctuation, ſ, ligatures, diacritics kept.
* ``reading@1``: invisible format characters removed (soft hyphen, zero-width characters, word joiner, BOM); NFKC;
  quotes and apostrophes to ``'``, dashes and hyphens to ``-``; a hyphen at a line end joined to the next line;
  casefolded; whitespace runs to one space; trimmed.
* ``alnum@1``: NFC; casefolded; only letters and digits (Unicode categories L and N) kept, every run of anything
  else one space; trimmed.

U+FFFD (an illegible character in a ground truth) survives every lane.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

REPLACEMENT = "�"
_WS = re.compile(r"\s+")
_INVISIBLE = {ord(c): None for c in "­​‌‍⁠﻿"}
_QUOTES = {ord(c): "'" for c in "'’‘ʼ`´“”„\""}
_HYPHENS = {ord(c): "-" for c in "‐‑‒–—―−"}
_DEHYPHENATE = re.compile(r"-[ \t]*\n\s*")


def _diplomatic(t: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", t)).strip()


def _reading(t: str) -> str:
    t = unicodedata.normalize("NFKC", t.translate(_INVISIBLE)).translate(_QUOTES).translate(_HYPHENS)
    return _WS.sub(" ", _DEHYPHENATE.sub("", t).casefold()).strip()


def _alnum(t: str) -> str:
    t = unicodedata.normalize("NFC", t).casefold()
    kept = "".join(c if c == REPLACEMENT or unicodedata.category(c)[0] in "LN" else " " for c in t)
    return _WS.sub(" ", kept).strip()


#: lane edition -> its normalization
LANES: dict[str, Callable[[str], str]] = {"diplomatic@1": _diplomatic, "reading@1": _reading, "alnum@1": _alnum}


def lane(name: str) -> str:
    """The lane edition ``name`` stands for (an id alone: its latest edition); unknown is a ``KeyError``."""
    if name in LANES:
        return name
    editions = sorted((k for k in LANES if k.split("@")[0] == name), key=lambda k: int(k.split("@")[1]))
    if not editions:
        raise KeyError(f"unknown lane {name!r}; lanes: {sorted(LANES)}")
    return editions[-1]


def normalize(text: str, name: str) -> str:
    """``text`` through the lane ``name``."""
    return LANES[lane(name)](text or "")
