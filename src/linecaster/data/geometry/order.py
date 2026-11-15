"""Region post-processing shared by layout steps: overlap suppression, plain XY-cut reading order and
slotting unordered regions into an order a model gave. XY-Cut++, which also reads the regions' labels, is in
``xy_cut_plus_plus``.

The functions take any objects with a ``bbox`` (a ``BBox``) and a mutable ``order`` (int or None). The orders take a
writing ``direction`` (``linecaster.data.writing.DIRECTIONS``, default ``horizontal-lr``): the boxes are seen in its
frame (``frames``), so "top" and "left" mean the start of a column and of a row in that direction."""
from __future__ import annotations

from typing import Sequence

from .frames import boxes_in_frame, framed
from .types import BBox


def suppress_contained(regions: Sequence, max_containment: float = 0.8) -> list:
    """Drop a region when most of its area lies inside a larger region (the text would be read twice).

    The larger region survives regardless of score; ``max_containment`` is the fraction of the
    smaller box covered by the larger one above which it is dropped.
    """
    keep = []
    by_area = sorted(regions, key=lambda r: -(r.bbox.width * r.bbox.height))
    for r in by_area:
        area = max(r.bbox.width * r.bbox.height, 1e-6)
        if any(r.bbox.intersection_area(k.bbox) / area > max_containment for k in keep):
            continue
        keep.append(r)
    return keep


def xy_cut_order(boxes: Sequence[BBox], min_gap: float = 1.0, direction: str | None = None) -> list[int]:
    """Return the indices of ``boxes`` in reading order.

    Recursively splits the set at the largest whitespace gap: horizontally (a gap spanning the full
    width, top group first) whenever one exists, otherwise vertically (left group first); groups that
    cannot be split are ordered by their top edge, then left edge. In the frame of ``direction``: right to left
    the right group first; vertical, a gap between columns first, the right column first (``vertical-rl``).
    """
    idx = list(range(len(boxes)))
    return _order(idx, boxes_in_frame(boxes, direction), min_gap)


def _order(idx: list[int], boxes: Sequence[BBox], min_gap: float) -> list[int]:
    if len(idx) <= 1:
        return idx
    for axis in ("y", "x"):
        groups = _split(idx, boxes, axis, min_gap)
        if len(groups) > 1:
            return [i for g in groups for i in _order(g, boxes, min_gap)]
    return sorted(idx, key=lambda i: (boxes[i].y0, boxes[i].x0))


def _split(idx: list[int], boxes: Sequence[BBox], axis: str, min_gap: float) -> list[list[int]]:
    lo = (lambda b: b.y0) if axis == "y" else (lambda b: b.x0)
    hi = (lambda b: b.y1) if axis == "y" else (lambda b: b.x1)
    ordered = sorted(idx, key=lambda i: lo(boxes[i]))
    groups, current, reach = [], [ordered[0]], hi(boxes[ordered[0]])
    for i in ordered[1:]:
        if lo(boxes[i]) - reach >= min_gap:
            groups.append(current)
            current, reach = [i], hi(boxes[i])
        else:
            current.append(i)
            reach = max(reach, hi(boxes[i]))
    groups.append(current)
    return groups


def place_unordered(regions: Sequence, direction: str | None = None) -> None:
    """Give regions without an ``order`` a place among those that have one, in place.

    An unordered region goes after the last ordered region that ends above its center and overlaps
    it horizontally (falling back to any region whose center is above it), so a page number at the
    top comes first, a missed line follows the paragraph above it and a drop capital precedes its
    paragraph. When no region carries an order the whole set is ordered with plain XY-cut
    (``xy_cut_order``; the ``LineAssigner`` of released recipes reaches this with orphan rows alone, where
    XY-Cut++ would order some pages differently). Ranks are renumbered 0..n-1. Above and left are in the frame of
    ``direction``.
    """
    regions = framed(regions, direction)
    ordered = sorted((r for r in regions if r.order is not None), key=lambda r: r.order)
    if not ordered:
        for rank, i in enumerate(xy_cut_order([r.bbox for r in regions])):
            regions[i].order = rank
        return
    unordered = sorted((r for r in regions if r.order is None), key=lambda r: (r.bbox.y0, r.bbox.x0))
    seq = list(ordered)
    for o in unordered:
        ob = o.bbox
        cy = (ob.y0 + ob.y1) / 2
        above = [i for i, r in enumerate(seq) if r.bbox.y1 <= cy and min(ob.x1, r.bbox.x1) > max(ob.x0, r.bbox.x0)]
        if not above:
            above = [i for i, r in enumerate(seq) if (r.bbox.y0 + r.bbox.y1) / 2 < cy]
        seq.insert(max(above) + 1 if above else 0, o)
    for rank, r in enumerate(seq):
        r.order = rank
