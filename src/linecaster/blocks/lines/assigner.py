"""Line blocks without a model: assigning detected lines to layout regions and ordering them.

``LineAssigner`` follows a page-level line detector (lines found once on the whole page):
each line goes to the region it overlaps most; lines outside every region (a page number the layout
model missed, marginalia) become their own ``text`` regions, one per visual row, slotted into the
reading order; duplicates are dropped and lines are ordered row by row within each region.

The list order of ``Transcription.lines`` afterwards is the processing order a recogniser follows
(regions in the layout step's order, orphan rows last, rows within each region); ``reading_order``
is the reading rank (regions by reading order, then rows). Line ids are ``<region id>_l<n>``.
"""
from __future__ import annotations

import numpy as np

from ...data.geometry import BBox, bbox_of, xywh
from ...data.geometry.order import place_unordered
from ...data.page import Page
from ...data.transcription import Line, Region
from ..base.page import PageBlock

SKIP_LABELS = frozenset({"picture", "chart"})


class _R:
    """A region as the ordering helpers see it: ``bbox`` from the polygon, a mutable ``order``."""

    def __init__(self, region: Region):
        self.region, self.bbox, self.order = region, bbox_of(region.polygon), region.reading_order
        self.lines: list[Line] = []


def _lb(line: Line) -> BBox:
    return bbox_of(line.polygon) if line.polygon else BBox(line.bbox[0], line.bbox[1], line.bbox[0] + line.bbox[2],
                                                           line.bbox[1] + line.bbox[3])


def _owner(line: Line, regions: list[_R]) -> _R | None:
    lb = _lb(line)
    best, best_area = None, 0.0
    for r in regions:
        a = lb.intersection_area(r.bbox)
        if a > best_area:
            best, best_area = r, a
    return best


def rows(lines: list[Line], overlap: float = 0.5) -> list[list[Line]]:
    """Visual rows: a line joins the current row when it vertically overlaps the row's top line."""
    out: list[list[Line]] = []
    for ln in sorted(lines, key=lambda l: _lb(l).y0):
        if out:
            ref = _lb(min(out[-1], key=lambda r: _lb(r).y0))
            b = _lb(ln)
            inter = min(ref.y1, b.y1) - max(ref.y0, b.y0)
            if inter >= overlap * min(ref.height, b.height):
                out[-1].append(ln)
                continue
        out.append([ln])
    return [sorted(row, key=lambda r: _lb(r).x0) for row in out]


def dedupe(lines: list[Line], max_containment: float = 0.7) -> list[Line]:
    """Drop a line box that lies mostly inside another (detectors sometimes emit a fragment twice)."""
    keep: list[Line] = []
    for ln in sorted(lines, key=lambda l: -(_lb(l).width * _lb(l).height)):
        b = _lb(ln)
        area = max(b.width * b.height, 1e-6)
        if not any(b.intersection_area(_lb(k)) / area > max_containment for k in keep):
            keep.append(ln)
    return keep


def order_rows(lines: list[Line]) -> list[Line]:
    """De-duplicate, then order lines row by row (top to bottom, left to right), recording the row."""
    out = []
    for i, row in enumerate(rows(dedupe(lines))):
        for ln in row:
            ln.row = i
            out.append(ln)
    return out


class LineAssigner(PageBlock):
    """Assign page-level lines to the layout regions and order them (see the module docstring).

    Regions labelled in ``skip_labels`` take no lines (pictures); with ``formulas_separately`` formula
    regions take none either (a formula step reads them as LaTeX), and lines inside them are dropped.
    """

    name = "line assigner"

    def __init__(self, transcription: str = "ocr_new", skip_labels=SKIP_LABELS, formulas_separately: bool = True):
        super().__init__()
        self.transcription, self.skip_labels, self.formulas_separately = transcription, frozenset(skip_labels), formulas_separately

    def _wants_lines(self, region: Region) -> bool:
        if region.label in self.skip_labels:
            return False
        return not (region.label == "formula" and self.formulas_separately)

    def process_page(self, doc, page: Page) -> Page:
        t = page.transcription(self.transcription)
        contents = [_R(r) for r in t.regions]
        ocr = [c for c in contents if self._wants_lines(c.region)]
        orphans: list[Line] = []
        for ln in t.lines:
            owner = _owner(ln, ocr)
            if owner is not None:
                ln.region_id = owner.region.id
                owner.lines.append(ln)
            elif _owner(ln, contents) is None:   # not inside a picture either
                orphans.append(ln)
            else:
                self.stat_update("lines_in_skipped_regions")
        if orphans:
            for i, row in enumerate(rows(orphans)):
                pts = np.concatenate([np.asarray(ln.polygon, dtype=float) for ln in row])
                b = BBox.of(pts)
                region = Region(id=f"orphan_{i}", label="text", raw_label="orphan", polygon=b.polygon.tolist(),
                                bbox=xywh(b), score=1.0, reading_order=None)
                c = _R(region)
                c.lines = list(row)
                for ln in c.lines:
                    ln.region_id = region.id
                contents.append(c)
            place_unordered(contents)
            ocr = [c for c in contents if self._wants_lines(c.region)]
            self.stat_update("orphan_rows", value=len(rows(orphans)))
        for c in ocr:
            c.lines = order_rows(c.lines)
        for c in contents:
            c.region.reading_order = c.order
        processing = [(c, k, ln) for c in contents for k, ln in enumerate(c.lines)]
        reading = sorted(processing, key=lambda x: (x[0].order if x[0].order is not None else 1 << 30, x[1]))
        rank = {id(ln): i for i, (_, _, ln) in enumerate(reading)}
        lines = []
        for c, k, ln in processing:
            ln.id = f"{c.region.id}_l{k}"
            ln.reading_order = rank[id(ln)]
            lines.append(ln)
        t.regions = [c.region for c in contents]
        t.lines = lines
        self.stat_update("lines", value=len(lines))
        return page
