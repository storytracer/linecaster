"""Line blocks without a model: assigning detected lines to layout regions and ordering them.

``LineAssigner`` follows a page-level line detector (lines found once on the whole page):
each line goes to the region it overlaps most; lines outside every region (a page number the layout
model missed, marginalia) become their own ``text`` regions, one per visual row, slotted into the
reading order; duplicates are classified ``duplicate`` and lines are ordered row by row within each region.

The assigner sets each detected line's ``region`` (a line that has one already keeps it) and adds a
``ReadingOrder`` (regions by reading order, then rows; each line's row within its region), both by its annotator
(step ``assignment``). The list order of ``Transcription.lines`` afterwards is the processing order a recognizer
follows (regions in the layout step's order, orphan rows last, rows within each region). Line ids stay as the line
step gave them.
"""
from __future__ import annotations

import time

from ...data.geometry import BBox
from ...data.geometry.order import place_unordered
from ...data.page import Page
from ...data.transcription import Annotator, Line, Region, Transcription
from ...text.typography import hidden, line_bbox, union, zone_bbox
from ..base.page import PageBlock

SKIP_LABELS = frozenset({"picture", "chart"})


class _R:
    """A region as the ordering helpers see it: ``bbox`` from the polygon (else the box), its Docling ``label``, a
    mutable ``order`` (its reading rank)."""

    def __init__(self, region: Region, label: str, order: int | None):
        self.region, self.bbox, self.label, self.order = region, zone_bbox(region), label, order
        self.lines: list[Line] = []


def _lb(line: Line) -> BBox:
    return line_bbox(line)


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


def order_rows(lines: list[Line]) -> tuple[list[Line], dict[str, int]]:
    """De-duplicate, then order lines row by row (top to bottom, left to right): the lines kept, in order, and each
    one's row."""
    out, row_of = [], {}
    for i, row in enumerate(rows(dedupe(lines))):
        for ln in row:
            row_of[ln.id] = i
            out.append(ln)
    return out, row_of


def _free_id(t: Transcription, stem: str, n: int) -> tuple[str, int]:
    """The first ``<stem>_<k>``, ``k >= n``, that no zone of ``t`` has (regions and lines share their ids)."""
    taken = {z.id for z in [*t.regions, *t.lines]}
    while f"{stem}_{n}" in taken:
        n += 1
    return f"{stem}_{n}", n


class LineAssigner(PageBlock):
    """Assigns the lines detected on the whole page to the layout regions and orders them row by row.

    Each line without a region goes to the region it overlaps most (a line that has one keeps it); lines outside
    every region (a page number the layout model missed, marginalia) become their own ``text`` regions
    (``orphan_<n>``, raw label ``orphan``), one per visual row, slotted into the reading order; a line that lies
    mostly inside another is classified ``status`` ``duplicate``, and a line inside a region that takes none
    ``status`` ``removed``. Afterwards the list order of ``lines`` is the order a recognizer follows (regions in the
    layout step's order, orphan rows last, rows within each region), and a new reading order ranks regions by
    reading order, then rows. Everything it adds is by its annotator, ``Annotator(kind="rule", step="assignment",
    name="line assigner")`` with its settings, ``seconds`` and ``datetime``; line ids stay.

    Reads ``lines`` and ``regions``; adds ``line_regions``; replaces ``regions`` (the orphan regions),
    ``reading_order`` and ``lines`` (their order). Stats: ``lines_in_skipped_regions``, ``orphan_rows`` (the rows
    that became regions), ``lines``.

    Args:
        transcription: the transcription whose lines and regions it works on.
        skip_labels: region labels (Docling labels) that take no lines (default pictures and charts).
        formulas_separately: formula regions take no lines either and the lines inside them are removed, for a
            formula step that reads them as LaTeX; ``False``: formula regions get lines like text regions.
    """

    name = "line assigner"
    parts_read = ("lines", "regions")
    parts_added = ("line_regions",)
    parts_replaced = ("regions", "reading_order", "lines")      # orphan regions, line order

    def __init__(self, transcription: str = "ocr_new", skip_labels=SKIP_LABELS, formulas_separately: bool = True):
        super().__init__()
        self.transcription, self.skip_labels, self.formulas_separately = transcription, frozenset(skip_labels), formulas_separately

    def _wants_lines(self, c: _R) -> bool:
        if c.label in self.skip_labels:
            return False
        return not (c.label == "formula" and self.formulas_separately)

    def process_page(self, doc, page: Page) -> Page:
        from ..base.rule import now

        start, began = now()
        t = page.transcription(self.transcription)
        a = t.add_annotator(Annotator(kind="rule", step="assignment", name="line assigner",
                                      settings={"skip_labels": sorted(self.skip_labels),
                                                "formulas_separately": self.formulas_separately}))
        ranks = t.region_ranks()
        contents = [_R(r, t.label(r.id), ranks.get(r.id)) for r in t.regions if not hidden(t, r.id)]
        by_id = {c.region.id: c for c in contents}
        ocr = [c for c in contents if self._wants_lines(c)]
        orphans: list[Line] = []
        dropped: list[Line] = []                 # classified duplicate or removed
        others: list[Line] = []                  # with a region the assigner does not order
        for ln in t.lines:
            assigned = t.region_of(ln)
            if assigned is not None:
                (by_id[assigned].lines if assigned in by_id else others).append(ln)
                continue
            owner = _owner(ln, ocr)
            if owner is not None:
                ln.region = owner.region.id
                owner.lines.append(ln)
            elif _owner(ln, contents) is None:   # not inside a picture either
                orphans.append(ln)
            else:
                t.classify(a, ln.id, "status", "removed", assignment__reason="in a region that takes no lines")
                dropped.append(ln)
                self.stat_update("lines_in_skipped_regions")
        if orphans:
            n = 0
            orphan_rows = rows(orphans)
            for row in orphan_rows:
                rid, n = _free_id(t, "orphan", n)
                b = union([_lb(ln) for ln in row])
                region = t.add_region(a, rid, [b.x0, b.y0, b.width, b.height], b.polygon.tolist(), label="orphan",
                                      role="text", confidence=1.0)
                c = _R(region, "text", None)
                c.lines = list(row)
                for ln in c.lines:
                    ln.region = region.id
                contents.append(c)
            place_unordered(contents)
            ocr = [c for c in contents if self._wants_lines(c)]
            self.stat_update("orphan_rows", value=len(orphan_rows))
        row_of: dict[str, int] = {}
        for c in ocr:
            kept, found = order_rows(c.lines)
            for ln in c.lines:
                if ln.id not in found:
                    t.classify(a, ln.id, "status", "duplicate")
                    dropped.append(ln)
            c.lines, row_of = kept, {**row_of, **found}
        processing = [(c, k, ln) for c in contents for k, ln in enumerate(c.lines)]
        reading = sorted(processing, key=lambda x: (x[0].order if x[0].order is not None else 1 << 30, x[1]))
        regions = [c.region.id for c in sorted((c for c in contents if c.order is not None), key=lambda c: c.order)]
        ordered = [ln for _, _, ln in reading] + others
        t.add_order(a, regions, [ln.id for ln in ordered], [row_of.get(ln.id, 0) for ln in ordered])
        placed = {id(ln) for ln in [*ordered, *dropped]}
        t.lines = [ln for _, _, ln in processing] + others + [ln for ln in t.lines if id(ln) not in placed] + dropped
        self.stat_update("lines", value=len(processing))
        t.annotators[a].measurements.update({"seconds": round(time.perf_counter() - start, 4), "datetime": began})
        return page
