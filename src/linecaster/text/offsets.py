"""Offsets through a change of text: where a span ``[start, end)`` of a text stands after the text changed (a
normalization, an edit applied, rows joined)."""
from __future__ import annotations

from difflib import SequenceMatcher


def moved(old: str, new: str):
    """A function moving a span ``[start, end)`` of ``old`` onto ``new`` (another form of the same text): through
    the parts both share unchanged; a span's start in a changed part goes to that part's start, its end to its end
    (a span on a half that became the whole word covers the word; one on removed text is empty). A position on the
    edge of an unchanged part moves with it: a span that ends where a change begins does not take the change in."""
    if old == new:
        return lambda a, e: (a, e)
    ops = SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
    equal = [op for op in ops if op[0] == "equal"]

    def at(pos: int, end: bool) -> int:
        for _, i1, i2, j1, _ in equal:
            if i1 <= pos <= i2:
                return j1 + pos - i1
        for tag, i1, i2, j1, j2 in ops:
            if i1 <= pos <= i2:
                return j2 if end else j1
        return len(new)

    return lambda a, e: (at(a, False), at(e, True))
