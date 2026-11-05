"""Unicode scripts for the rule-based steps: which strategy decides, by the script of the characters around a
decision.

Scripts are named by their ISO 15924 codes (``Latn``, ``Hebr``, ``Arab``, ``Hani``), the values of Unicode's
``Script`` property, and matched with the ``regex`` package's ``\\p{Script=...}``. ``"*"`` stands for every script.
Characters of the scripts Common (``Zyyy``: spaces, punctuation, digits, most hyphens) and Inherited (``Zinh``:
combining marks) belong to no script of their own: a decision is made by the script of the nearest characters that
have one, and a run of text keeps them with the characters they follow.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

import regex

#: every script (an engine's ``scripts``; a preset's ``by_script`` default)
ALL = "*"
#: Unicode's scripts without letters of their own
COMMON, INHERITED = "Zyyy", "Zinh"
#: the form of an ISO 15924 code
CODE = re.compile(r"^[A-Z][a-z]{3}$")


def check_code(code: str) -> str:
    """``code`` if it is an ISO 15924 code Unicode knows as a script (or ``"*"``), else a ``ValueError``."""
    if code == ALL:
        return code
    if not CODE.match(code):
        raise ValueError(f"{code!r} is not an ISO 15924 script code (four letters, e.g. Latn, Hebr) or '*'")
    try:
        regex.compile(rf"\p{{Script={code}}}")
    except regex.error:
        raise ValueError(f"{code!r} is not a Unicode script") from None
    return code


def covers(scripts: Iterable[str], code: str) -> bool:
    """Whether a strategy declaring ``scripts`` covers script ``code``."""
    scripts = tuple(scripts)
    return ALL in scripts or code in scripts


class Classifier:
    """Which of the given scripts a character belongs to: one of ``codes``, ``"*"`` for any other script, or
    ``None`` for a Common or Inherited character."""

    def __init__(self, codes: Iterable[str]):
        self.codes = tuple(check_code(c) for c in codes if c != ALL)
        groups = [rf"(?P<s{i}>\p{{Script={c}}})" for i, c in enumerate(self.codes)]
        self._pattern = regex.compile("|".join([*groups, rf"(?P<neutral>[\p{{Script={COMMON}}}\p{{Script={INHERITED}}}])"]))

    def __call__(self, ch: str) -> str | None:
        m = self._pattern.match(ch)
        if m is None:
            return ALL
        if m.lastgroup == "neutral":
            return None
        return self.codes[int(m.lastgroup[1:])]

    def at(self, before: str, after: str) -> str:
        """The script of a decision between ``before`` and ``after`` (a row end and the next row's start): that of
        the last character of ``before`` that has one, else of the first such character of ``after``; ``"*"``
        when neither has one."""
        for ch in reversed(before):
            if (s := self(ch)) is not None:
                return s
        for ch in after:
            if (s := self(ch)) is not None:
                return s
        return ALL

    def runs(self, text: str) -> list[tuple[str, str]]:
        """``text`` as runs of one script each, ``(script, run)``; Common and Inherited characters stay in the run
        before them (at the start of the text, in the first run)."""
        out: list[list] = []
        pending = ""                                     # neutral characters before the first scripted one
        for ch in text:
            s = self(ch)
            if s is None:
                if out:
                    out[-1][1] += ch
                else:
                    pending += ch
            elif out and out[-1][0] == s:
                out[-1][1] += ch
            else:
                out.append([s, pending + ch])
                pending = ""
        if pending:
            out.append([ALL, pending])
        return [(s, r) for s, r in out]
