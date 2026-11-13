"""Lanes: versioned normalizations a rendered text goes through before it is counted, the same for both sides of a
comparison. A lane is named ``<id>@<edition>``; a released edition never changes (a change is a new edition).

* ``diplomatic@1``: NFC; whitespace runs to one space; trimmed. Case, punctuation, ſ, ligatures, diacritics kept.
* ``reading@1``: markup removed (special tokens, box arrays, HTML tags of a fixed list, Markdown headings,
  bullets and rules, LaTeX macros, and the characters `` ` * | ~ { } $ \\ ``); NFKC; invisible format characters
  removed (soft hyphen, zero-width characters, word joiner, BOM); single quotes, apostrophes, backtick and acute
  accent to ``'``, curly double quotes to ``"``, the dashes U+2010 to U+2015 to ``-``; a hyphen at a line end joined
  to the next line; casefolded; whitespace runs to one space; trimmed.
* ``alnum@1``: NFC; casefolded; only letters and digits (Unicode categories L and N) kept, every run of anything
  else one space; trimmed.
* ``ascii-alnum@1``: HTML tags removed; lowercased; only the ASCII letters and digits kept (``[a-z0-9]+``), the
  runs joined by single spaces: what is not ASCII (accented letters, ſ, ligatures) separates words.

U+FFFD (an illegible character in a ground truth) survives every lane.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

REPLACEMENT = "�"
_WS = re.compile(r"\s+")
_INVISIBLE = {ord(c): None for c in "­​‌‍⁠﻿"}
_QUOTES = {ord(c): "'" for c in "'\u2019\u2018\u02bc`\u00b4"}
_QUOTES.update({ord(c): '"' for c in "\u201c\u201d"})
_HYPHENS = {ord(c): "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015"}
_DEHYPHENATE = re.compile(r"-\s*\n\s*")


def _diplomatic(t: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", t)).strip()


#: HTML tag names the reading lane removes (a fixed list: angle brackets around other words are text)
_HTML_TAGS = ("a|b|big|blockquote|br|caption|center|code|col|colgroup|div|em|figcaption|figure|font|h[1-6]|hr|i|img|"
              "li|mark|ol|p|pre|s|small|span|strike|strong|sub|sup|table|tbody|td|tfoot|th|thead|tr|tt|u|ul")
#: markup the reading lane removes, as a space: special tokens, box arrays, HTML tags, Markdown headings, bullets
#: and rules, LaTeX macros, and the marks of emphasis, tables and formulas
_MARKUP = [re.compile(r"<\|/?[A-Za-z0-9_]+\|>"), re.compile(r"\[\[\s*\d[\d,\s]*\]\]"),
           re.compile(rf"</?(?:{_HTML_TAGS})(?:\s[^>\n]{{0,80}})?\s*/?>", re.I),
           re.compile(r"^[ \t]*#{1,6}[ \t]+", re.M), re.compile(r"^[ \t]*[-*+][ \t]+", re.M),
           re.compile(r"^[ \t]*[-=_*]{3,}[ \t]*$", re.M), re.compile(r"\\[a-zA-Z]+\*?"),
           re.compile(r"[`*|~{}$\\]")]


def _reading(t: str) -> str:
    for rx in _MARKUP:
        t = rx.sub(" ", t)
    t = unicodedata.normalize("NFKC", t).translate(_INVISIBLE).translate(_QUOTES).translate(_HYPHENS)
    return _WS.sub(" ", _DEHYPHENATE.sub("", t).casefold()).strip()


_TAG = re.compile(r"<[^>]+>")
_ASCII_WORD = re.compile(r"[a-z0-9\ufffd]+")


def _ascii_alnum(t: str) -> str:
    return " ".join(_ASCII_WORD.findall(_TAG.sub(" ", t).lower()))


def _alnum(t: str) -> str:
    t = unicodedata.normalize("NFC", t).casefold()
    kept = "".join(c if c == REPLACEMENT or unicodedata.category(c)[0] in "LN" else " " for c in t)
    return _WS.sub(" ", kept).strip()


#: lane edition -> its normalization
LANES: dict[str, Callable[[str], str]] = {"diplomatic@1": _diplomatic, "reading@1": _reading, "alnum@1": _alnum,
                                          "ascii-alnum@1": _ascii_alnum}


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
