"""XY-Cut++ reading order for layout regions that come without one.

The method of Liu, Li and Wei, "XY-Cut++: Advanced Layout Ordering via Hierarchical Mask Mechanism on a Novel
Benchmark" (arXiv:2504.10258v3), on region boxes, their labels and the page size:

1. **Page furniture**: ``page_header`` regions lead and ``page_footer`` regions close the order, each group top to
   bottom, left to right. The paper leaves them out; PaddleX's ``xycut_enhanced`` orders them this way.
2. **Pre-mask**: titles, visual elements and footnotes are masked by their label. A text region is
   *cross-layout*, and masked too, when it is wider than ``beta`` times the median width of the page's text
   regions and its width covers at least two other text regions side by side (a sweep from left to right that
   counts each column once).
3. **Pre-cut**: a title or visual region whose center lies within ``center_tolerance`` of the page width from the
   page's vertical center line, with no other region (visual ones aside) to its left or right at the same height,
   is *isolated*; the page's body is cut into bands at the top of every isolated region.
4. **Density-driven cuts**, per band: τ_d, the area of the band's cross-layout regions over the area of its other
   text regions, picks horizontal cuts first (τ_d > ``theta_v``) or vertical cuts first; the band's unmasked text
   regions are ordered by recursive cuts at whitespace gaps of at least ``min_gap``, the other axis when the
   first gives no cut, top then left where neither does. A band without unmasked text is ordered by the cuts
   alone, nothing masked.
5. **Cross-modal matching**: the masked regions come back in label priority, cross-layout, title, vision,
   others, each in reading position (top, then left). Each is attached to the ordered region (the band's text
   and what came back before it) with the smallest distance D = M²·φ1 + M·φ2 + φ3 + φ4 / M, M the page's larger
   side: φ1 = 1 when the two differ in direction or their projection overlap is below ``tau_overlap`` (else 0),
   φ2 the gap between their edges weighted by the direction the candidate lies in (``edge_weights``), φ3 the
   candidate's top edge (minus its bottom edge when a cross-layout region lies below it), φ4 its left edge. The
   first candidate in order wins a tie. After each stage the regions are sorted by the rank of their anchor, then
   top, then left.

Label categories, linecaster's region labels (DoclingDocument's vocabulary) to the paper's: ``title`` and
``section_header`` are *title*; ``picture``, ``chart``, ``table``, ``caption`` and ``seal`` are *vision*;
``footnote`` is *others* (masked and matched last); ``page_header`` and ``page_footer`` are page furniture (step 1);
every other label (``text``, ``list_item``, ``formula``, ``code``, ``reference``, ...) is text, cross-layout or not
by its geometry. Layouts are read as horizontal (left to right, top to bottom); the paper's weights for vertical
layouts are not used.

Sources: the paper; where it is ambiguous or inconsistent, the authors' implementation decides:
``get_layout_ordering`` and its helpers in ``paddlex/inference/pipelines/layout_parsing/utils.py`` of
github.com/liushuai35/PaddleXrc at commit 7873ab38662e3277091520f4259f090bc197fee4 (Apache License 2.0, Copyright
(c) 2024 PaddlePaddle Authors). Followed from it, not copied: the edge gap with direction weights
(``_nearest_edge_distance``, ``_get_weights``), the directions in φ1 (``_get_bbox_direction``, a visual region always
horizontal), the column sweep of cross-layout detection (``_get_layout_property``), the isolation test (horizontal
centering and no text at the sides, ``_get_sub_category``) and the sort after each stage. Where the paper and that
code differ in a value (τ_overlap 0.3 against 0.01, θ_v 0.9 against 1.0, scale-dependent term weights against
fixed ones), the paper's is the default. NOTES.md (2026-11-07) records each choice.
"""
from __future__ import annotations

from bisect import bisect_right
from statistics import median
from typing import Mapping, Sequence

from .order import _split
from .types import BBox

TITLE, VISION, OTHERS, TEXT, CROSS = "title", "vision", "others", "text", "cross-layout"

#: region label -> the paper's category; labels not listed are text (cross-layout or not by geometry)
CATEGORIES: dict[str, str] = {
    "title": TITLE, "section_header": TITLE,
    "picture": VISION, "chart": VISION, "table": VISION, "caption": VISION, "seal": VISION,
    "footnote": OTHERS,
}
#: page furniture: leads (``page_header``) and closes (``page_footer``) the order, outside the method
LEADING, TRAILING = "page_header", "page_footer"
#: the order in which masked regions come back (the paper's label priority)
PRIORITY = (CROSS, TITLE, VISION, OTHERS)
#: per category, the weights of the edge gap to a candidate when the region lies to its left, to its right, above
#: it, below it (the paper's Eq. 14 for horizontal layouts; vision takes the "otherwise" row)
EDGE_WEIGHTS: dict[str, tuple[float, float, float, float]] = {
    TITLE: (1.0, 0.1, 0.1, 1.0),
    CROSS: (1.0, 1.0, 0.1, 1.0),
    VISION: (1.0, 1.0, 1.0, 0.1),
    OTHERS: (1.0, 1.0, 1.0, 0.1),
}


def xy_cut_plus_plus_order(boxes: Sequence[BBox], labels: Sequence[str], page_size: tuple[float, float], *,
                           beta: float = 1.3, theta_v: float = 0.9, tau_overlap: float = 0.3,
                           center_tolerance: float = 0.2,
                           edge_weights: Mapping[str, Sequence[float]] | None = None,
                           min_gap: float = 1.0) -> list[int]:
    """Returns the indices of ``boxes`` in XY-Cut++ reading order.

    Pure and deterministic: the order depends only on the arguments (ties go to the lower index). The method's
    steps and the label categories are described above.

    Args:
        boxes: the regions' boxes, in page pixels.
        labels: the regions' labels (DoclingDocument's vocabulary), one per box.
        page_size: the page's width and height, in the boxes' pixels.
        beta: a text region wider than ``beta`` times the median text width can be cross-layout (the paper's 1.3).
        theta_v: the density τ_d above which a band is cut horizontally first (the paper's 0.9).
        tau_overlap: the projection overlap (on the narrower region) below which a matching pair is invalid (φ1;
            the paper's 0.3).
        center_tolerance: how far from the page's vertical center line, as a share of the page width, an isolated
            region's center may lie (the paper's 0.2).
        edge_weights: per category (``title``, ``cross-layout``, ``vision``, ``others``), the four direction
            weights of the edge gap; ``None``: the paper's (``EDGE_WEIGHTS``).
        min_gap: the narrowest whitespace gap, in pixels, a cut is made at (1, as ``xy_cut_order``).
    """
    if len(labels) != len(boxes):
        raise ValueError(f"{len(boxes)} boxes but {len(labels)} labels")
    weights = {**EDGE_WEIGHTS, **(edge_weights or {})}
    width, height = page_size
    scale = max(width, height, 1.0)
    category = [CATEGORIES.get(label, TEXT) for label in labels]

    def by_position(idx):
        return sorted(idx, key=lambda i: (boxes[i].y0, boxes[i].x0, i))

    leading = by_position(i for i, label in enumerate(labels) if label == LEADING)
    trailing = by_position(i for i, label in enumerate(labels) if label == TRAILING)
    body = [i for i, label in enumerate(labels) if label not in (LEADING, TRAILING)]

    # 2. pre-mask: cross-layout text
    text = [i for i in body if category[i] == TEXT]
    median_width = median(boxes[i].width for i in text) if text else 0.0
    by_x = sorted(text, key=lambda i: (boxes[i].x0, boxes[i].width, i))
    cross = {i for i in text if boxes[i].width > beta * median_width and _columns(i, by_x, boxes) >= 2}

    # 3. pre-cut at isolated titles and visual regions
    cuts = sorted({boxes[i].y0 for i in body if category[i] in (TITLE, VISION)
                   and _isolated(i, body, boxes, category, width, center_tolerance)})
    bands: list[list[int]] = [[] for _ in range(len(cuts) + 1)]
    for i in body:
        bands[bisect_right(cuts, boxes[i].y0)].append(i)

    order = list(leading)
    for band in bands:
        single = [i for i in band if category[i] == TEXT and i not in cross]
        if not single:
            order += _cut(band, boxes, "y", min_gap)
            continue
        # 4. density-driven cuts
        single_area = sum(boxes[i].width * boxes[i].height for i in single)
        cross_area = sum(boxes[i].width * boxes[i].height for i in band if i in cross)
        first = "y" if cross_area / single_area > theta_v else "x"
        seq = _cut(single, boxes, first, min_gap)
        # 5. cross-modal matching
        stage = {i: (CROSS if i in cross else category[i]) for i in band if i not in single}
        for s in PRIORITY:
            pending = by_position(i for i in stage if stage[i] == s)
            if not pending:
                continue
            rank = {i: k for k, i in enumerate(seq)}
            candidates = list(seq)
            for p in pending:
                best = min(candidates, key=lambda o: _distance(boxes[p], boxes[o], s, category[p] == VISION,
                                                               weights[s], tau_overlap, scale))
                rank[p] = rank[best]
                candidates.append(p)
            seq = sorted(candidates, key=lambda i: (rank[i], boxes[i].y0, boxes[i].x0, i))
        order += seq
    return order + trailing


def _cut(idx: list[int], boxes: Sequence[BBox], first: str, min_gap: float) -> list[int]:
    """Recursive cuts at whitespace gaps, along ``first`` (``y``: horizontal cuts) before the other axis."""
    if len(idx) <= 1:
        return list(idx)
    for axis in (first, "x" if first == "y" else "y"):
        groups = _split(idx, boxes, axis, min_gap)
        if len(groups) > 1:
            return [i for g in groups for i in _cut(g, boxes, first, min_gap)]
    return sorted(idx, key=lambda i: (boxes[i].y0, boxes[i].x0, i))


def _columns(i: int, by_x: list[int], boxes: Sequence[BBox]) -> int:
    """How many other text regions the width of region ``i`` covers side by side, swept left to right: a region
    counts when it overlaps the part of the width the regions counted so far leave uncovered."""
    lo, hi = boxes[i].x0, boxes[i].x1
    n = 0
    for j in by_x:
        if j == i:
            continue
        if min(hi, boxes[j].x1) - max(lo, boxes[j].x0) > 0:
            n += 1
            lo = min(hi, boxes[j].x1)
            if lo >= hi:
                break
    return n


def _isolated(i: int, body: list[int], boxes: Sequence[BBox], category: list[str], page_width: float,
              tolerance: float) -> bool:
    """Whether region ``i`` is centered on the page and no other region but a visual one sits beside it."""
    b = boxes[i]
    if abs((b.x0 + b.x1) / 2 - page_width / 2) > tolerance * page_width:
        return False
    for j in body:
        o = boxes[j]
        if j == i or category[j] == VISION:
            continue
        if (o.x1 <= b.x0 or o.x0 >= b.x1) and min(o.y1, b.y1) > max(o.y0, b.y0):
            return False
    return True


def _distance(a: BBox, b: BBox, stage: str, visual: bool, weights: Sequence[float], tau_overlap: float,
              scale: float) -> float:
    """The paper's matching distance D of pending region ``a`` to ordered candidate ``b``."""
    horizontal_a = visual or a.width >= a.height
    horizontal_b = 3 * b.width >= b.height
    if horizontal_a:
        overlap, base = min(a.x1, b.x1) - max(a.x0, b.x0), min(a.width, b.width)
    else:
        overlap, base = min(a.y1, b.y1) - max(a.y0, b.y0), min(a.height, b.height)
    projection = max(overlap, 0.0) / base if base > 0 else 0.0
    phi1 = 1.0 if horizontal_a != horizontal_b or projection < tau_overlap else 0.0
    phi2 = _edge_gap(a, b, weights)
    phi3 = -b.y1 if stage == CROSS and a.y0 > b.y1 else b.y0
    phi4 = b.x0
    return scale * scale * phi1 + scale * phi2 + phi3 + phi4 / scale


def _edge_gap(a: BBox, b: BBox, weights: Sequence[float]) -> float:
    """The gap between the edges of ``a`` and ``b``, each axis weighted by the side ``a`` lies on (left, right,
    above, below ``b``): the sum of both axes when they are diagonal, the one axis when they are side by side or
    one above the other, 0 when they overlap."""
    if a.intersection_area(b) > 0:
        return 0.0
    dx = dy = float("inf")
    if a.x1 <= b.x0:
        dx = (b.x0 - a.x1) * weights[0]
    elif a.x0 >= b.x1:
        dx = (a.x0 - b.x1) * weights[1]
    if a.y1 <= b.y0:
        dy = (b.y0 - a.y1) * weights[2]
    elif a.y0 >= b.y1:
        dy = (a.y0 - b.y1) * weights[3]
    if dx != float("inf") and dy != float("inf"):
        return dx + dy
    gap = min(dx, dy)
    return 0.0 if gap == float("inf") else gap
