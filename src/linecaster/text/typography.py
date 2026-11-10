"""Retyper: what the typesetter's sizes and initials say about a page's regions, on a ``Transcription``.

The engine ``typography.ratios.v1`` (``linecaster.engines.typography``) runs it, every threshold a field of
``Ratios`` (the constants below are their defaults). It runs after recognition (and tables), before page composition. All rules
are ratios to the page's own body type, measured from the row heights the line step delivered (a row = the lines
of one region with the same ``Line.row``; its box = the union of their boxes, derived from the polygons):

- **Type-size ladder** (``Region.heading_level``): the body size is the median row height of the
  page's ``text`` regions (all their non-empty rows). A ``section_header`` whose rows are body-sized
  (ratio below ``DEMOTE``, 1.2) becomes ``text``; otherwise headings (``section_header``, ``title``)
  get a level from the ratio: ``LEVELS`` = 2.5 and above level 1, 1.7 level 2, else level 3.
- **Headline split**: a ``text`` region whose first one to three non-empty rows are at least
  ``SPLIT`` (1.6) times taller than the median of the rows after them, and than the body size, carries
  a headline the layout model merged into the body. Those rows become a ``section_header`` region of
  their own, placed just before it in reading order.
- **Drop capitals**: a region whose ``raw_label`` ends in ``drop-capital`` is glued onto the first line
  of the ``text`` region it overlaps most (else the nearest one below right) and removed.
- **Page-number confidence**: a ``page_header``/``page_footer`` region from a layout model's number
  class (``raw_label`` ending in ``number``) whose text is empty or was read with a mean character
  confidence below ``PAGE_NUMBER_MIN_CONF`` (0.75) is an ornament or a blob and is removed.

Ids and where things go:

- A split-off headline is region ``<region id>_head`` (``raw_label`` = the original's + ``/split``);
  its lines keep their ids (``<region id>_l<n>``) and get the new ``region_id``. The body region's
  polygon and bbox shrink to the box around its remaining lines.
- A drop capital's letter is prepended to the target line's ``text`` (``line.extra["drop_capital"]``
  records it; the line's words are left as the recognizer gave them).
- Removed regions (drop capitals, uncertain page numbers) leave ``regions`` together with their lines;
  each is recorded in ``Transcription.extra["retyper_dropped"]`` (region id, label, raw label, text,
  reason, confidence), so nothing is lost silently.
- Reading order: regions with an order are re-ranked 0..n-1 (a headline sorts just before its body
  region); ``Transcription.lines`` is rebuilt in region list order (the processing order) and every
  line's ``reading_order`` re-derived (regions by reading order, then their lines).

Mean character confidence: the region mean is the line means (``Line.confidence``) weighted by line
length, which is the mean of the per-character confidences over the region up to float rounding.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..data.geometry import BBox, bbox_of, xywh
from ..data.transcription import Line, Region, Transcription

PAGE_NUMBER_MIN_CONF = 0.75
DEMOTE = 1.2
SPLIT = 1.6
LEVELS = ((2.5, 1), (1.7, 2), (0.0, 3))
HEADING_LABELS = ("section_header", "title")
MAX_HEADLINE_ROWS = 3


@dataclass(frozen=True)
class Ratios:
    """The rules' thresholds (ratios to the page's body size) and the labels they read; the defaults are the
    ``ratios`` preset's values."""

    page_number_min_conf: float = PAGE_NUMBER_MIN_CONF
    demote: float = DEMOTE
    split: float = SPLIT
    levels: tuple[tuple[float, int], ...] = LEVELS
    max_headline_rows: int = MAX_HEADLINE_ROWS
    heading_labels: tuple[str, ...] = HEADING_LABELS


DEFAULT_RATIOS = Ratios()


@dataclass
class RetypeStats:
    body_size: float = 0.0
    demoted: int = 0
    split: int = 0
    leveled: int = 0
    drop_capitals: int = 0
    numbers_dropped: int = 0
    examples: list[str] = field(default_factory=list)

    def note(self, kind: str, text: str) -> None:
        if len(self.examples) < 200:
            self.examples.append(f"{kind}: {text[:60]}")

    def counts(self) -> dict:
        return {"body_size": self.body_size, "leveled": self.leveled, "demoted": self.demoted, "split": self.split,
                "drop_capitals": self.drop_capitals, "numbers_dropped": self.numbers_dropped}


@dataclass
class Row:
    text: str
    bbox: BBox
    index: int


def line_bbox(ln: Line) -> BBox:
    if ln.polygon:
        return bbox_of(ln.polygon)
    x, y, w, h = ln.bbox
    return BBox(x, y, x + w, y + h)


class Content:
    """One region with its lines (in the transcription's line order), as the rules see it."""

    def __init__(self, region: Region, lines: list[Line]):
        self.region, self.lines = region, lines

    @property
    def bbox(self) -> BBox:
        return bbox_of(self.region.polygon)

    def rows(self) -> list[Row]:
        grouped: dict[int, list[Line]] = {}
        for ln in self.lines:
            grouped.setdefault(ln.row, []).append(ln)
        out = []
        for i, k in enumerate(sorted(grouped)):
            boxes = [line_bbox(ln) for ln in grouped[k]]
            b = BBox(min(x.x0 for x in boxes), min(x.y0 for x in boxes), max(x.x1 for x in boxes), max(x.y1 for x in boxes))
            out.append(Row(" ".join(ln.text for ln in grouped[k] if ln.text), b, i))
        return out

    @property
    def text(self) -> str:
        return "\n".join(r.text for r in self.rows())


def heading_level(ratio: float, levels: tuple[tuple[float, int], ...] = LEVELS) -> int:
    for threshold, level in levels:
        if ratio >= threshold:
            return level
    return levels[-1][1]


def row_heights(c: Content) -> list[float]:
    return [r.bbox.height for r in c.rows() if r.text.strip()]


def body_size(contents: list[Content]) -> float:
    heights = [h for c in contents if c.region.label == "text" for h in row_heights(c)]
    if not heights:
        heights = [h for c in contents for h in row_heights(c)]
    return float(np.median(heights)) if heights else 0.0


def region_size(c: Content) -> float:
    heights = row_heights(c)
    return float(np.median(heights)) if heights else 0.0


def _set_polygon(region: Region, b: BBox) -> None:
    region.polygon = b.polygon.tolist()
    region.bbox = xywh(b)


# ------------------------------------------------------------------------------------------ rules
def level_headings(contents: list[Content], body: float, stats: RetypeStats, r: Ratios = DEFAULT_RATIOS) -> None:
    for c in contents:
        if c.region.label not in r.heading_labels or body <= 0:
            continue
        size = region_size(c)
        if size <= 0:
            continue
        ratio = size / body
        if ratio < r.demote and c.region.label == "section_header":
            c.region.label = "text"
            c.region.heading_level = None
            stats.demoted += 1
            stats.note("demoted", c.text)
        else:
            c.region.heading_level = heading_level(ratio, r.levels)
            stats.leveled += 1


def split_leading_heading(c: Content, body: float, stats: RetypeStats, r: Ratios = DEFAULT_RATIOS) -> Content | None:
    rows = [r for r in c.rows() if r.text.strip()]
    if c.region.label != "text" or len(rows) < 2:
        return None
    heights = [r.bbox.height for r in rows]
    tall = 0
    while tall < min(r.max_headline_rows, len(rows) - 1):
        rest = heights[tall + 1:]
        if heights[tall] >= r.split * float(np.median(rest)) and heights[tall] >= r.split * body:
            tall += 1
        else:
            break
    if tall == 0:
        return None
    head_rows = {rows[i].index for i in range(tall)}   # row indices, compared with Line.row
    keep = [ln for ln in c.lines if ln.row not in head_rows]
    move = [ln for ln in c.lines if ln.row in head_rows]
    if not keep or not move:
        return None
    hb = BBox.of(np.concatenate([np.asarray(ln.polygon, dtype=float) for ln in move]))
    region = Region(id=f"{c.region.id}_head", label="section_header", raw_label=c.region.raw_label + "/split",
                    polygon=hb.polygon.tolist(), bbox=xywh(hb), score=c.region.score, reading_order=c.region.reading_order)
    for ln in move:
        ln.region_id = region.id
    head = Content(region, move)
    c.lines = keep
    _set_polygon(c.region, BBox.of(np.concatenate([np.asarray(ln.polygon, dtype=float) for ln in keep])))
    stats.split += 1
    stats.note("split", head.text)
    return head


def merge_drop_capitals(contents: list[Content], stats: RetypeStats, dropped: list[dict]) -> list[Content]:
    drops = [c for c in contents if c.region.raw_label.endswith("drop-capital")]
    if not drops:
        return contents
    drop_ids = {id(d) for d in drops}
    texts = [c for c in contents if c.region.label == "text" and id(c) not in drop_ids and c.lines]
    removed = set()
    for d in drops:
        letter = d.text.strip()
        if not letter or not texts:
            continue
        db = d.bbox
        target = max(texts, key=lambda c: c.bbox.intersection_area(db))
        if target.bbox.intersection_area(db) <= 0:
            below = [c for c in texts if c.bbox.y1 > db.y0 and c.bbox.x1 > db.x0]
            if not below:
                continue
            target = min(below, key=lambda c: (abs(c.bbox.y0 - db.y0), c.bbox.x0 - db.x1))
        first = target.lines[0]
        first.text = letter + (first.text or "").lstrip()
        first.extra["drop_capital"] = letter
        removed.add(id(d))
        dropped.append(_dropped(d, "drop capital merged into " + first.id))
        stats.drop_capitals += 1
        stats.note("drop capital", first.text)
    return [c for c in contents if id(c) not in removed]


def mean_confidence(c: Content) -> float:
    num = den = 0.0
    for ln in c.lines:
        if ln.confidence is not None and ln.text:
            num += ln.confidence * len(ln.text)
            den += len(ln.text)
    return num / den if den else 0.0


def drop_uncertain_numbers(contents: list[Content], stats: RetypeStats, dropped: list[dict],
                           r: Ratios = DEFAULT_RATIOS) -> list[Content]:
    out = []
    for c in contents:
        if c.region.label in ("page_header", "page_footer") and c.region.raw_label.endswith("number"):
            conf = mean_confidence(c)
            if not c.text.strip() or conf < r.page_number_min_conf:
                stats.numbers_dropped += 1
                stats.note("number dropped", f"{c.text.strip()!r} at {conf:.2f}")
                dropped.append(_dropped(c, "uncertain page number", conf))
                continue
        out.append(c)
    return out


def _dropped(c: Content, reason: str, confidence: float | None = None) -> dict:
    return {"region_id": c.region.id, "label": c.region.label, "raw_label": c.region.raw_label, "text": c.text,
            "lines": [ln.id for ln in c.lines], "reason": reason, "confidence": confidence}


def retype(t: Transcription, stats: RetypeStats | None = None, ratios: Ratios = DEFAULT_RATIOS) -> RetypeStats:
    """Apply the rules to a transcription in place (regions may be added or removed); returns the stats (the
    engine records them as the step's measurements)."""
    stats = stats if stats is not None else RetypeStats()
    by_region: dict[str, list[Line]] = {}
    for ln in t.lines:
        by_region.setdefault(ln.region_id, []).append(ln)
    contents = [Content(r, by_region.pop(r.id, [])) for r in t.regions]
    unassigned = [ln for lines in by_region.values() for ln in lines]   # lines outside every region stay as they are
    body = body_size(contents)
    stats.body_size = body
    out: list[Content] = []
    for c in contents:
        head = split_leading_heading(c, body, stats, ratios) if body > 0 else None
        if head is not None:
            out.append(head)
        out.append(c)
    level_headings(out, body, stats, ratios)
    dropped: list[dict] = []
    out = merge_drop_capitals(out, stats, dropped)
    out = drop_uncertain_numbers(out, stats, dropped, ratios)
    ordered = [c for c in out if c.region.reading_order is not None]
    ordered.sort(key=lambda c: (c.region.reading_order, 0 if c.region.id.endswith("_head") else 1))
    for rank, c in enumerate(ordered):
        c.region.reading_order = rank
    t.regions = [c.region for c in out]
    t.lines = [ln for c in out for ln in c.lines] + unassigned
    reading = sorted(((c, k, ln) for c in out for k, ln in enumerate(c.lines)),
                     key=lambda x: (x[0].region.reading_order if x[0].region.reading_order is not None else 1 << 30, x[1]))
    for rank, (_, _, ln) in enumerate(reading):
        ln.reading_order = rank
    for k, ln in enumerate(unassigned, start=len(reading)):
        ln.reading_order = k
    if dropped:
        t.extra.setdefault("retyper_dropped", []).extend(dropped)
    return stats
