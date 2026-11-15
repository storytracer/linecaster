"""Lanes: the comparison strategies both sides of a scored text go through before it is counted (catalog strategies
with ``use: comparison``, made of the same normalizations a written text may use; ``linecaster.catalog``,
``Catalog.strategy``). A lane is named by its strategy's id: ``alnum`` (the default), ``reading``, ``diplomatic``,
``alnum-nonmark``, ``ascii-alnum``, or normalizations joined by ``+``. The release versions them, as every catalog
entry; a score names each lane with its hash.

The lane names from before 0.10 (``alnum@2``) resolve to the strategy that does the same, with a warning
(``LEGACY``): ``alnum@2`` is ``alnum``, ``alnum@1`` ``alnum-nonmark``, ``diplomatic@1`` ``diplomatic``,
``ascii-alnum@1`` ``ascii-alnum``, and ``reading@1`` ``reading``, which no longer joins a hyphen at a line's end (no
dehyphenation by default; a strategy may name one).

U+FFFD (an illegible character in a ground truth) survives every lane.
"""
from __future__ import annotations

import re
import warnings

REPLACEMENT = "\ufffd"
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
#: the markup the ``markup`` normalization removes (``reading``, ``alnum``), public for callers that must keep
#: positions (replace each match by as many spaces, then normalize the pieces); the catalog entry holds the same
MARKUP = tuple(_MARKUP)

#: lane names from before 0.10 -> the comparison strategy that does the same
LEGACY = {"diplomatic@1": "diplomatic", "reading@1": "reading", "alnum@1": "alnum-nonmark", "alnum@2": "alnum",
          "ascii-alnum@1": "ascii-alnum"}
#: the lane scored when a benchmark or a call names none
DEFAULT_LANE = "alnum"
_CACHE: dict = {}


def lane(name: str) -> str:
    """The comparison strategy ``name`` stands for: a strategy's id, normalizations joined by ``+``, or a lane name
    from before 0.10 (``LEGACY``, with a warning); an unknown one is a ``KeyError``."""
    from ..catalog.registry import EditionWarning

    if name in LEGACY:
        warnings.warn(f"lane {name}: lanes are catalog strategies since linecaster 0.10; it is {LEGACY[name]!r}"
                      + (" (without its hyphen join)" if name == "reading@1" else ""), EditionWarning, stacklevel=2)
        return LEGACY[name]
    try:
        resolve(name)
    except Exception as e:  # noqa: BLE001 - CatalogError: not a comparison strategy
        raise KeyError(f"unknown lane {name!r}: {e}") from None
    return name


def resolve(name: str):
    """The resolved comparison strategy of lane ``name`` (``linecaster.catalog.registry.ResolvedStrategy``), cached
    per catalog."""
    from ..catalog.registry import catalog

    c = catalog()
    key = (id(c), name)
    if key not in _CACHE:
        _CACHE[key] = c.strategy(LEGACY.get(name, name), use="comparison")
    return _CACHE[key]


def normalize(text: str, name: str) -> str:
    """``text`` through the lane ``name``."""
    return resolve(lane(name)).text(text or "")


def uncovered(declared, name: str, output: str = "literal") -> list[str]:
    """The conventions check: the normalizations a ground truth declares it embodies (``Source.normalized``) that
    neither the lane ``name`` nor the output strategy's character rules apply, themselves or by one that subsumes
    them (``ResolvedStrategy.covers``). Each one is a difference the comparison counts that is the ground truth's
    convention, not the output's error (a ground truth that writes ſ as s, scored by a lane that keeps ſ)."""
    from ..catalog.registry import catalog
    from ..catalog.schema import TEXT_RULES

    lane_s = resolve(lane(name))
    out = catalog().strategy(output, use="output")
    out_chars = [n for n in out.normalizations if next(iter(n.rule)) in TEXT_RULES]   # scoring applies these only
    return [n for n in declared
            if not lane_s.covers(n) and not any(x.id == n or n in x.subsumes for x in out_chars)]
