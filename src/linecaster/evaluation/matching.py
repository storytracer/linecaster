"""Matching the ground truth's elements to the output's (``linecaster.evaluation.elements``), so that content is compared
where it is, whatever the output's segmentation and order: OmniDocBench's methodology (its elements matched before
they are compared), done deterministically and for any script.

Both sides' contents come here already written by the output strategy and normalized by the matching lane, as their
units (grapheme clusters by default): each unit becomes a number, U+FFFD of the ground truth one that equals nothing.

* **Containment** of a shorter element ``a`` in a longer ``b``: ``1 - λ(a in b) / |a|``, with ``λ`` the edit distance
  of ``a`` aligned in full against any stretch of ``b`` (Sellers' semi-global distance, ``local_distance``): a
  paragraph's half that an output gives as its own block is contained in the paragraph. A subsequence measure would
  call any short text contained in any long one; this is local.
* **Similarity**: ``1 - Levenshtein / max(|a|, |b|)``.
* **Candidates**: the elements of the other side sharing the most n-grams of units (``ngram``, default 3; an n-gram
  in more than ``stop`` elements counts for none), at most ``candidates`` (default 8) each.
* **Homes**: each element's home is the candidate on the other side it is contained in or contains with the highest
  containment (at least ``containment``, default 0.5), then similarity, then the nearer relative position in reading
  order, then the lower index; an element shorter than ``short`` units (default 4) needs that similarity instead,
  since containment means nothing for ``12``.
* **Groups**: the connected components of the homes. A group is ``one`` (one element each side), ``split`` (one
  ground-truth element, several output elements), ``merge`` (the reverse), ``many``, ``missed`` (a ground-truth
  element without a partner) or ``extra`` (an output element without one).

A group's sides are compared as wholes (``linecaster.evaluation.metrics.score_elements``), so the element score
forgives the order between groups (it is no bound on the page score: a wrong match costs); one output element
holding the whole page is one group, the page-level comparison. Past ``max_cells`` aligned units (default 5·10⁸) a page is one group (``page``).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from linecaster.evaluation.lanes import REPLACEMENT


@dataclass(frozen=True)
class Settings:
    """How elements are matched (module docstring); a benchmark's ``elements`` settings."""

    containment: float = 0.5
    short: int = 4
    ngram: int = 3
    candidates: int = 8
    stop: int = 64
    max_cells: int = 500_000_000


@dataclass(frozen=True)
class Group:
    """Matched elements: ``kind`` (module docstring), the ground truth's and the output's element indices, in order."""

    kind: str
    truth: tuple[int, ...]
    output: tuple[int, ...]


def encode(truth: Sequence[Sequence[str]], output: Sequence[Sequence[str]]) -> tuple[list[np.ndarray],
                                                                                    list[np.ndarray]]:
    """Both sides' units (lists of units per element) as arrays of numbers, one alphabet for the page; a ground
    truth's illegible unit (U+FFFD) as -1 and an output's as -2, which equal nothing."""
    ids: dict[str, int] = {}

    def side(elements, wild):
        out = []
        for units in elements:
            out.append(np.fromiter((wild if REPLACEMENT in u else ids.setdefault(u, len(ids)) for u in units),
                                   dtype=np.int64, count=len(units)))
        return out

    return side(truth, -1), side(output, -2)


def local_distance(a: np.ndarray, b: np.ndarray) -> int:
    """The edit distance of ``a``, aligned in full, against the best stretch of ``b`` (free gaps at ``b``'s ends)."""
    if len(a) == 0:
        return 0
    if len(b) == 0:
        return len(a)
    idx = np.arange(len(b) + 1)
    prev = np.zeros(len(b) + 1, dtype=np.int64)
    neq = np.empty(len(b), dtype=np.int64)
    for i in range(1, len(a) + 1):
        np.not_equal(b, a[i - 1], out=neq)
        if a[i - 1] < 0:                                  # an illegible unit equals nothing
            neq[:] = 1
        cur = np.empty_like(prev)
        cur[0] = i
        np.minimum(prev[:-1] + neq, prev[1:] + 1, out=cur[1:])
        cur = np.minimum.accumulate(cur - idx) + idx       # insertions along the row
        prev = cur
    return int(prev.min())


def containment(a: np.ndarray, b: np.ndarray) -> float:
    """How much of the shorter of ``a`` and ``b`` lies in the longer (module docstring)."""
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) == 0:
        return 0.0
    return 1.0 - local_distance(short, long) / len(short)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    from rapidfuzz.distance import Levenshtein

    m = max(len(a), len(b))
    if m == 0:
        return 1.0
    return 1.0 - Levenshtein.distance(a.tolist(), b.tolist()) / m


def _grams(x: np.ndarray, n: int) -> set[tuple[int, ...]]:
    v = [u for u in x.tolist() if u >= 0]
    if len(v) < n:
        return {tuple(v)} if v else set()
    return {tuple(v[k:k + n]) for k in range(len(v) - n + 1)}


def _candidates(src: list[set], dst: list[set], k: int, stop: int) -> list[list[int]]:
    index: dict[tuple, list[int]] = {}
    for j, grams in enumerate(dst):
        for g in sorted(grams):
            index.setdefault(g, []).append(j)
    out = []
    for grams in src:
        shared: Counter = Counter()
        for g in sorted(grams):
            hits = index.get(g, ())
            if len(hits) > stop:
                continue
            shared.update(hits)
        out.append([j for j, _ in sorted(shared.items(), key=lambda x: (-x[1], x[0]))[:k]])
    return out


def match(truth: Sequence[np.ndarray], output: Sequence[np.ndarray], settings: Settings = Settings()) -> list[Group]:
    """The groups of a page's elements (module docstring), ground-truth groups in the ground truth's order, then the
    output's extras in the output's order."""
    G, O = len(truth), len(output)
    if G == 0 or O == 0:
        return [Group("missed", (g,), ()) for g in range(G)] + [Group("extra", (), (o,)) for o in range(O)]
    total = sum(len(x) for x in truth) * max(len(x) for x in output) * settings.candidates
    if total > settings.max_cells:
        return [Group("page", tuple(range(G)), tuple(range(O)))]
    tg = [_grams(x, settings.ngram) for x in truth]
    og = [_grams(x, settings.ngram) for x in output]
    cand_o = _candidates(og, tg, settings.candidates, settings.stop)      # output -> truth candidates
    cand_g = _candidates(tg, og, settings.candidates, settings.stop)
    pairs = {(g, o) for o, gs in enumerate(cand_o) for g in gs} | {(g, o) for g, os in enumerate(cand_g) for o in os}
    score: dict[tuple[int, int], tuple[float, float]] = {}
    for g, o in sorted(pairs):
        a, b = truth[g], output[o]
        score[(g, o)] = (containment(a, b), similarity(a, b))

    def eligible(g: int, o: int) -> bool:
        c, s = score[(g, o)]
        if min(len(truth[g]), len(output[o])) < settings.short:
            return s >= settings.containment
        return c >= settings.containment

    def key(g: int, o: int):
        c, s = score[(g, o)]
        return (c, s, -abs(g / G - o / O))

    parent = list(range(G + O))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        a, b = find(x), find(y)
        if a != b:
            parent[max(a, b)] = min(a, b)

    linked_g, linked_o = set(), set()
    for o in range(O):
        best = [g for g in cand_o[o] if eligible(g, o)]
        if best:
            g = max(best, key=lambda g: (key(g, o), -g))
            union(g, G + o)
            linked_g.add(g)
            linked_o.add(o)
    for g in range(G):
        best = [o for o in cand_g[g] if eligible(g, o)]
        if best:
            o = max(best, key=lambda o: (key(g, o), -o))
            union(g, G + o)
            linked_g.add(g)
            linked_o.add(o)
    components: dict[int, tuple[list[int], list[int]]] = {}
    for g in range(G):
        components.setdefault(find(g), ([], []))[0].append(g)
    for o in range(O):
        components.setdefault(find(G + o), ([], []))[1].append(o)
    groups = []
    for gs, os in components.values():
        if not os:
            groups.extend(Group("missed", (g,), ()) for g in gs)
        elif not gs:
            groups.extend(Group("extra", (), (o,)) for o in os)
        else:
            kind = "one" if len(gs) == len(os) == 1 else "split" if len(gs) == 1 else "merge" if len(os) == 1 \
                else "many"
            groups.append(Group(kind, tuple(sorted(gs)), tuple(sorted(os))))
    return sorted(groups, key=lambda grp: (0, grp.truth[0]) if grp.truth else (1, grp.output[0]))


__all__ = ["Group", "Settings", "containment", "encode", "local_distance", "match", "similarity"]
