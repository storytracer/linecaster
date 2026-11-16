"""Reading order, scored apart from content: of the ground truth's elements that matched (``linecaster.scoring.
matching``), how far the output's order of them is from the ground truth's.

Each matched ground-truth element takes the position of the output element it is matched to (the first in the
output's order where several are); elements merged into one output element tie. Two measures:

* **Kendall distance** (``discordant / pairs``): the share of pairs of elements the output puts the other way round;
  tied pairs count as neither;
* **index edit distance** (``edits / length``): the Levenshtein distance between the ground truth's order of the
  elements and the order the output gives them, OmniDocBench's reading-order measure.

Neither needs geometry: each side's order is its own reading order, which already follows its writing direction
(right to left, vertical columns), so the measures hold for every direction.
"""
from __future__ import annotations

from collections.abc import Sequence


def kendall(positions: Sequence[float]) -> tuple[int, int]:
    """(discordant pairs, comparable pairs) of ``positions`` (the output's positions of the ground truth's elements in
    the ground truth's order): a pair is discordant when the later element comes first; ties are not comparable."""
    discordant = pairs = 0
    for a in range(len(positions)):
        for b in range(a + 1, len(positions)):
            if positions[a] == positions[b]:
                continue
            pairs += 1
            discordant += positions[a] > positions[b]
    return discordant, pairs


def index_edits(positions: Sequence[float]) -> tuple[int, int]:
    """(edits, length): the Levenshtein distance between the ground truth's order of its elements (0, 1, ...) and the
    order the output gives them (sorted by ``positions``, ties in the ground truth's order)."""
    from rapidfuzz.distance import Levenshtein

    order = sorted(range(len(positions)), key=lambda k: (positions[k], k))
    return Levenshtein.distance(list(range(len(positions))), order), len(positions)


__all__ = ["index_edits", "kendall"]
