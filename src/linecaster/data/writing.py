"""Writing systems in the data model: the values of the classification schemes ``language`` (a BCP 47 tag),
``script`` (an ISO 15924 code) and ``direction`` (a writing direction), and their checks.

A direction is one of ``DIRECTIONS``, the four writing modes of a page or block: ``horizontal-lr`` (lines left to
right, stacked top to bottom: Latin, Greek, Cyrillic, Devanagari, ...), ``horizontal-rl`` (lines right to left, top to
bottom: Arabic, Hebrew, ...), ``vertical-rl`` (columns top to bottom, stacked right to left: Chinese, Japanese and
Korean set vertically) and ``vertical-lr`` (columns top to bottom, left to right: Mongolian). They map to CSS's
``writing-mode`` and ``direction``, to PAGE-XML's ``readingDirection`` and ``textLineOrder``, and to hOCR's ``dir``.
"""
from __future__ import annotations

import re

#: the writing directions (the ``direction`` scheme's values)
DIRECTIONS = ("horizontal-lr", "horizontal-rl", "vertical-rl", "vertical-lr")

# RFC 5646's syntax of a language tag (well-formedness, not validity: subtags are not looked up), case-insensitive
_ALNUM = "[a-z0-9]"
_LANGTAG = (rf"(?:[a-z]{{2,3}}(?:-[a-z]{{3}}){{0,3}}|[a-z]{{4}}|[a-z]{{5,8}})"     # language, extlang
            rf"(?:-[a-z]{{4}})?"                                              # script
            rf"(?:-(?:[a-z]{{2}}|[0-9]{{3}}))?"                               # region
            rf"(?:-(?:{_ALNUM}{{5,8}}|[0-9]{_ALNUM}{{3}}))*"                  # variants
            rf"(?:-[0-9a-wyz](?:-{_ALNUM}{{2,8}})+)*"                          # extensions
            rf"(?:-x(?:-{_ALNUM}{{1,8}})+)?")                                  # private use
_BCP47 = re.compile(rf"^(?:{_LANGTAG}|x(?:-{_ALNUM}{{1,8}})+|i-[a-z]{{2,8}})$", re.I)
_SCRIPT_CODE = re.compile(r"^[A-Z][a-z]{3}$")


def is_language(value: str) -> bool:
    """Whether ``value`` is a well-formed BCP 47 language tag (``en``, ``de-1901``, ``zh-Hant-TW``, ``grc``)."""
    return bool(_BCP47.match(value or ""))


def language_tag(value: str | None) -> str | None:
    """A source's language value as a BCP 47 tag, where it is one: trimmed, ``_`` as ``-`` (``en_US``); ``None`` for
    an empty or ill-formed value (``en US``, ``fra/lat``)."""
    v = (value or "").strip().replace("_", "-")
    return v if v and is_language(v) else None


def is_script(value: str) -> bool:
    """Whether ``value`` is shaped as an ISO 15924 code: four letters, the first a capital (``Latn``, ``Arab``,
    ``Jpan``, ``Latf``). ISO 15924 lists more codes than Unicode's Script property (combinations such as ``Jpan``,
    variants such as ``Latf`` for Fraktur), so the shape is checked, not a list."""
    return bool(_SCRIPT_CODE.match(value or ""))


def is_direction(value: str) -> bool:
    return value in DIRECTIONS


#: scheme -> its check, applied where a classification is made (``AnnotationSet.classify``)
CHECKS = {"language": is_language, "script": is_script, "direction": is_direction}


def check(scheme: str, value: str) -> str:
    """``value`` if it is one of ``scheme``'s (``CHECKS``), else a ``ValueError``; any value for other schemes."""
    ok = CHECKS.get(scheme)
    if ok is not None and not ok(value):
        what = {"language": "a well-formed BCP 47 language tag", "script": "an ISO 15924 script code (Latn, Arab)",
                "direction": f"one of {', '.join(DIRECTIONS)}"}[scheme]
        raise ValueError(f"{scheme}: {value!r} is not {what}")
    return value
