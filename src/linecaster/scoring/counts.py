"""Character edit counts of an output against a ground truth: the codepoint alignment's substitutions, deletions,
insertions and hits. A U+FFFD in the ground truth (an illegible character) is excluded from the errors and from the
reference length, whatever it is aligned with."""
from __future__ import annotations

from dataclasses import dataclass

from .lanes import REPLACEMENT


@dataclass(frozen=True)
class EditCounts:
    s: int = 0
    d: int = 0
    i: int = 0
    h: int = 0

    @property
    def n(self) -> int:
        """The counted reference length: hits, substitutions and deletions."""
        return self.s + self.d + self.h

    @property
    def errors(self) -> int:
        return self.s + self.d + self.i

    @property
    def cer(self) -> float | None:
        return self.errors / self.n if self.n else (None if not self.i else float("inf"))

    def __add__(self, other: "EditCounts") -> "EditCounts":
        return EditCounts(self.s + other.s, self.d + other.d, self.i + other.i, self.h + other.h)


def edit_counts(reference: str, output: str) -> EditCounts:
    """The edit counts of ``output`` against ``reference`` (both already normalized by one lane), codepoint by
    codepoint (Levenshtein, ``rapidfuzz``)."""
    try:
        from rapidfuzz.distance import Levenshtein
    except ImportError as e:            # pragma: no cover - the extra
        raise ImportError("scoring needs rapidfuzz: install linecaster[rapidfuzz]") from e
    wild = {k for k, c in enumerate(reference) if c == REPLACEMENT}
    s = d = i = 0
    touched = set()
    for op in Levenshtein.editops(reference, output):
        if op.tag == "insert":
            i += 1
            continue
        touched.add(op.src_pos)
        if op.src_pos in wild:
            continue
        if op.tag == "replace":
            s += 1
        else:
            d += 1
    h = len(reference) - len(touched) - len(wild - touched)
    return EditCounts(s, d, i, h)
