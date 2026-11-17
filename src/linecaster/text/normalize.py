"""Normalizations on text: the character rules of the catalog's normalizations (``linecaster.normalization``).

A normalization holds one rule. The character rules change a string and apply anywhere a text is written or two
texts are compared:

- ``unicode``: a Unicode normalization form, ``NFC`` or ``NFKC``;
- ``map``: a table, each key (a character or a sequence; the longest first) replaced by its value (``""`` removes
  it);
- ``patterns``: regular expressions, in order, each match replaced (by a space unless said otherwise); each compiled
  with Python's ``re``, or with the ``regex`` package when its ``engine`` says so (Unicode properties such as
  ``\\p{Ll}``);
- ``case``: Unicode case folding (``fold``) or lowercasing (``lower``);
- ``keep``: only the characters of the given Unicode categories, ranges and further characters; every run of others
  becomes one space;
- ``whitespace``: every run of whitespace one space, the text trimmed.
- ``latex``: each LaTeX formula as the characters it prints (``text``: ``linecaster.text.latex``), for comparison.

The structure rules (the source's edits, divided words, division marks, flow) act on a document's blocks
(``linecaster.document.strategy``); on a plain string they are an error. Nothing here is a default: a text changes only
by the normalizations a strategy names (``linecaster.catalog``: ``Catalog.strategy``).
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any

_WS = re.compile(r"\s+")


class StructureRule(ValueError):
    """A normalization of a document's structure applied to a plain string."""


@lru_cache(maxsize=256)
def _map_rx(items: tuple[tuple[str, str], ...]) -> re.Pattern:
    keys = sorted((k for k, _ in items), key=len, reverse=True)
    return re.compile("|".join(map(re.escape, keys)))


@lru_cache(maxsize=256)
def _patterns(items: tuple[tuple[str, tuple[str, ...], str, str], ...]) -> tuple[tuple[Any, str], ...]:
    out = []
    for match, flags, replace, engine in items:
        if engine == "regex":
            import regex as rx_engine
        else:
            rx_engine = re
        f = 0
        for x in flags:
            f |= getattr(rx_engine, x)
        out.append((rx_engine.compile(match, f), replace))
    return tuple(out)


@lru_cache(maxsize=64)
def _keeper(categories: tuple[str, ...], ranges: tuple[str, ...], also: str):
    rx = re.compile("[" + "".join(re.escape(r[0]) + "-" + re.escape(r[2]) if len(r) == 3 and r[1] == "-"
                                  else re.escape(r) for r in ranges) + "]") if ranges else None

    def kept(c: str) -> bool:
        return (c in also or (categories and unicodedata.category(c)[0] in categories)
                or (rx is not None and rx.match(c) is not None))

    return kept


def apply_rule(text: str, rule: dict[str, Any]) -> str:
    """``text`` through one rule (a normalization's ``rule``, as a dict with one key)."""
    (kind, value), = ((k, v) for k, v in rule.items() if v is not None)
    if kind == "unicode":
        return unicodedata.normalize(value, text)
    if kind == "map":
        if not value:
            return text
        rx = _map_rx(tuple(sorted(value.items())))
        return rx.sub(lambda m: value[m.group(0)], text)
    if kind == "patterns":
        for rx, replace in _patterns(tuple((p["match"], tuple(p.get("flags") or ()), p.get("replace", " "),
                                            p.get("engine", "re")) for p in value)):
            text = rx.sub(replace, text)
        return text
    if kind == "case":
        return text.casefold() if value == "fold" else text.lower()
    if kind == "keep":
        kept = _keeper(tuple(value.get("categories") or ()), tuple(value.get("ranges") or ()), value.get("also") or "")
        return "".join(c if kept(c) else " " for c in text)
    if kind == "whitespace":
        return _WS.sub(" ", text).strip()
    if kind == "latex":
        from linecaster.text.latex import latex_text

        return latex_text(text)
    raise StructureRule(f"the rule {kind!r} acts on a document's structure, not on a string")


def apply(text: str, rules: list[dict[str, Any]]) -> str:
    """``text`` through ``rules`` in order (each a normalization's ``rule``)."""
    for rule in rules:
        text = apply_rule(text, rule)
    return text
