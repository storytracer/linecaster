"""Character edit counts of an output against a ground truth: the alignment's substitutions, deletions, insertions and
hits, by grapheme cluster (what a reader sees as one character, Unicode's extended grapheme clusters, as OCR-D counts:
a letter with a combining mark is one) or, with ``unit="codepoint"``, by code point (as before 0.10). A U+FFFD in
the ground truth (an illegible character) is excluded from the errors and from the reference length, whatever it is
aligned with."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from linecaster.evaluation.lanes import REPLACEMENT

#: the units a character error rate counts in
UNITS = ("grapheme", "codepoint")


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


def units(text: str, unit: Literal["grapheme", "codepoint"] = "grapheme") -> list[str]:
    """``text`` as the units counted: its grapheme clusters, or its code points."""
    if unit == "codepoint":
        return list(text)
    if unit != "grapheme":
        raise ValueError(f"unit {unit!r}: one of {UNITS}")
    from uniseg.graphemecluster import grapheme_clusters

    return list(grapheme_clusters(text))


def edit_counts(reference: str, output: str, unit: Literal["grapheme", "codepoint"] = "grapheme") -> EditCounts:
    """The edit counts of ``output`` against ``reference`` (both already normalized by one lane), unit by unit
    (``units``; Levenshtein, ``rapidfuzz``)."""
    try:
        from rapidfuzz.distance import Levenshtein
    except ImportError as e:            # pragma: no cover - the extra
        raise ImportError("scoring needs rapidfuzz: install linecaster[rapidfuzz]") from e
    if unit == "codepoint":
        ref, out = reference, output
    else:
        ids: dict[str, int] = {}
        a, b = units(reference, unit), units(output, unit)
        ref = [ids.setdefault(x, len(ids)) for x in a]
        out = [ids.setdefault(x, len(ids)) for x in b]
        reference = a                                  # the units, for the illegible ones and the length
    wild = {k for k, c in enumerate(reference) if REPLACEMENT in c}
    s = d = i = 0
    touched = set()
    for op in Levenshtein.editops(ref, out):
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


def edit_counts_by(segments: list[str], output: str, unit: Literal["grapheme", "codepoint"] = "grapheme",
                   joiner: str = " ") -> list[EditCounts]:
    """The edit counts of ``output`` against the reference ``joiner.join(segments)``, attributed to its segments: a
    substitution or deletion to the segment of its reference unit (a joiner to the segment before it), an insertion
    to the segment of the reference unit before it (the first segment's when it comes first). The counts sum to
    ``edit_counts`` of the joined reference."""
    try:
        from rapidfuzz.distance import Levenshtein
    except ImportError as e:            # pragma: no cover - the extra
        raise ImportError("scoring needs rapidfuzz: install linecaster[rapidfuzz]") from e
    if not segments:
        return []
    ref_units: list[str] = []
    owner: list[int] = []
    for k, seg in enumerate(segments):
        parts = units(seg + (joiner if k < len(segments) - 1 else ""), unit)
        ref_units += parts
        owner += [k] * len(parts)
    out_units = units(output, unit)
    ids: dict[str, int] = {}
    ref = [ids.setdefault(x, len(ids)) for x in ref_units]
    out = [ids.setdefault(x, len(ids)) for x in out_units]
    wild = {k for k, c in enumerate(ref_units) if REPLACEMENT in c}
    s = [0] * len(segments)
    d = [0] * len(segments)
    i = [0] * len(segments)
    touched: set[int] = set()
    for op in Levenshtein.editops(ref, out):
        if op.tag == "insert":
            i[owner[op.src_pos - 1] if op.src_pos > 0 and ref else 0] += 1
            continue
        touched.add(op.src_pos)
        if op.src_pos in wild:
            continue
        (s if op.tag == "replace" else d)[owner[op.src_pos]] += 1
    n_seg = Counter(owner[k] for k in range(len(ref_units)) if k not in wild)
    t_seg = Counter(owner[k] for k in touched if k not in wild)
    return [EditCounts(s[k], d[k], i[k], n_seg[k] - t_seg[k]) for k in range(len(segments))]
