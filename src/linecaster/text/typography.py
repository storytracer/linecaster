"""Retyper: what the typesetter's sizes and initials say about a page's regions, on a ``Transcription``.

The engine ``typography.ratios.v1`` (``linecaster.engines.typography``) runs it, every threshold a field of
``Ratios`` (the constants below are their defaults). It runs after recognition (and tables), before page composition. All rules
are ratios to the page's own body type, measured from the row heights the line step delivered (a row = the lines
of one region on the same visual row, ``Transcription.rows``; its box = the union of their boxes, derived from the
polygons). Labels are Docling labels, as ``Transcription.label`` resolves them from the regions' content roles; a
region's own ``label`` is its layout model's raw label.

- **Type-size ladder** (``heading_level``): the body size is the median row height of the
  page's ``text`` regions (all their non-empty rows). A ``section_header`` whose rows are body-sized
  (ratio below ``DEMOTE``, 1.2) becomes ``text``; otherwise headings (``section_header``, ``title``)
  get a level from the ratio: ``LEVELS`` = 2.5 and above level 1, 1.7 level 2, else level 3.
- **Headline split**: a ``text`` region whose first one to three non-empty rows are at least
  ``SPLIT`` (1.6) times taller than the median of the rows after them, and than the body size, carries
  a headline the layout model merged into the body. Those rows become a ``section_header`` region of
  their own, placed just before it in reading order.
- **Drop capitals**: a region whose raw label ends in ``drop-capital`` is joined to the first line
  of the ``text`` region it overlaps most (else the nearest one below right) and removed.
- **Page-number confidence**: a ``page_header``/``page_footer`` region from a layout model's number
  class (raw label ending in ``number``) whose text is empty or was read with a mean character
  confidence below ``PAGE_NUMBER_MIN_CONF`` (0.75) is an ornament or a blob and is removed.

What the rules decide is added to the transcription by the step's annotator; nothing that was there changes:

- A label is a ``role`` classification (``linecaster.data.policy.classify_label``: a demoted section header is
  ``paragraph`` again), a heading level a ``heading_level`` classification.
- A split-off headline is region ``<region id>_head`` (``parent`` the region it came from, its raw label the
  original's + ``/split``, its box around the rows it took) with a ``section_header`` role; each of its lines
  keeps its id and gets a ``part_of`` link to it. The body region keeps its box; the rules measure it around its
  remaining lines.
- A drop capital's letter is prepended to the target line's text as a ``joined`` edit (``derived_from`` the
  drop capital's lines; the line's words are left as the recognizer gave them).
- A removed region (drop capitals, uncertain page numbers) is classified ``status`` ``removed``, with the reason
  (``typography__reason``) and, for a page number, the mean confidence; it keeps its lines, and the renderings
  leave it out (the default policy puts ``removed`` nowhere).
- Reading order: a new ``ReadingOrder`` when the order changed: the ranked regions in order, a headline just before
  its body region, removed regions left out; the lines by region rank, then in the regions' processing order
  (``Transcription.lines``), lines outside every region last.

Mean character confidence: the region mean is the line readings' confidences weighted by line length, which is the
mean of the per-character confidences over the region up to float rounding.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..data.geometry import BBox, bbox_of, xywh
from ..data.policy import DEFAULT_POLICY, classify_label
from ..data.transcription import AS_WRITTEN, Annotator, Edit, Line, Link, Region, Transcription, Zone

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


def zone_bbox(z: Zone) -> BBox:
    """A zone's box: from its polygon, else its ``box``."""
    if z.polygon:
        return bbox_of(z.polygon)
    x, y, w, h = z.box
    return BBox(x, y, x + w, y + h)


def line_bbox(ln: Line) -> BBox:
    return zone_bbox(ln)


def union(boxes: list[BBox]) -> BBox:
    return BBox(min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes), max(b.y1 for b in boxes))


class Content:
    """One region with its lines (in the transcription's line order), as the rules see it: its Docling label and
    heading level as the rules have decided them so far, and the box the rules measure (``box``: the region's, shrunk
    to its remaining lines after a headline split)."""

    def __init__(self, t: Transcription, region: Region, lines: list[Line], rows: dict[str, int], label: str,
                 rank: int | None, level: int | None = None):
        self.t, self.region, self.lines, self.rows_of = t, region, lines, rows
        self.label, self.rank, self.level = label, rank, level
        self.box = zone_bbox(region)

    @property
    def bbox(self) -> BBox:
        return self.box

    def text_of(self, ln: Line) -> str | None:
        return self.t.text_of(ln, AS_WRITTEN)

    def rows(self) -> list[Row]:
        grouped: dict[int, list[Line]] = {}
        for ln in self.lines:
            grouped.setdefault(self.rows_of.get(ln.id, 0), []).append(ln)
        out = []
        for i, k in enumerate(sorted(grouped)):
            b = union([line_bbox(ln) for ln in grouped[k]])
            out.append(Row(" ".join(x for ln in grouped[k] if (x := self.text_of(ln))), b, i))
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
    heights = [h for c in contents if c.label == "text" for h in row_heights(c)]
    if not heights:
        heights = [h for c in contents for h in row_heights(c)]
    return float(np.median(heights)) if heights else 0.0


def region_size(c: Content) -> float:
    heights = row_heights(c)
    return float(np.median(heights)) if heights else 0.0


# ------------------------------------------------------------------------------------------ rules
def level_headings(contents: list[Content], body: float, stats: RetypeStats, r: Ratios = DEFAULT_RATIOS,
                   annotator: int | None = None) -> None:
    for c in contents:
        if c.label not in r.heading_labels or body <= 0:
            continue
        size = region_size(c)
        if size <= 0:
            continue
        ratio = size / body
        if ratio < r.demote and c.label == "section_header":
            c.label, c.level = "text", None
            classify_label(c.t, annotator, c.region.id, "text")
            stats.demoted += 1
            stats.note("demoted", c.text)
        else:
            c.level = heading_level(ratio, r.levels)
            c.t.classify(annotator, c.region.id, "heading_level", c.level)
            stats.leveled += 1


def split_leading_heading(c: Content, body: float, stats: RetypeStats, r: Ratios = DEFAULT_RATIOS,
                          annotator: int | None = None) -> Content | None:
    rows = [r for r in c.rows() if r.text.strip()]
    if c.label != "text" or len(rows) < 2:
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
    visual = sorted({c.rows_of.get(ln.id, 0) for ln in c.lines})
    head_rows = {visual[rows[i].index] for i in range(tall)}       # the rows' keys in Transcription.rows
    keep = [ln for ln in c.lines if c.rows_of.get(ln.id, 0) not in head_rows]
    move = [ln for ln in c.lines if c.rows_of.get(ln.id, 0) in head_rows]
    if not keep or not move:
        return None
    t = c.t
    hb = union([line_bbox(ln) for ln in move])
    region = Region(annotator=annotator, id=f"{c.region.id}_head", label=c.region.label + "/split",
                    polygon=hb.polygon.tolist(), box=xywh(hb), parent=c.region.id, confidence=c.region.confidence)
    t.regions.insert(t.regions.index(c.region), region)
    classify_label(t, annotator, region.id, "section_header")
    for ln in move:
        t.links.append(Link(annotator=annotator, kind="part_of", source=ln.id, target=region.id))
    head = Content(t, region, move, c.rows_of, "section_header", c.rank)
    c.lines = keep
    c.box = union([line_bbox(ln) for ln in keep])
    stats.split += 1
    stats.note("split", head.text)
    return head


def merge_drop_capitals(contents: list[Content], stats: RetypeStats, annotator: int | None = None) -> list[Content]:
    drops = [c for c in contents if c.region.label.endswith("drop-capital")]
    if not drops:
        return contents
    drop_ids = {id(d) for d in drops}
    texts = [c for c in contents if c.label == "text" and id(c) not in drop_ids and c.lines]
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
        t = target.t
        first = target.lines[0]
        joined = letter + (target.text_of(first) or "").lstrip()
        t.edits.append(Edit(annotator=annotator, target=first.id, kind="joined", text=joined,
                            derived_from=[ln.id for ln in d.lines]))
        t.classify(annotator, d.region.id, "status", "removed", typography__reason="drop capital merged into " + first.id)
        removed.add(id(d))
        stats.drop_capitals += 1
        stats.note("drop capital", joined)
    return [c for c in contents if id(c) not in removed]


def mean_confidence(c: Content) -> float:
    num = den = 0.0
    for ln in c.lines:
        text = c.text_of(ln)
        conf = ln.reading.confidence if ln.reading is not None else None
        if conf is not None and text:
            num += conf * len(text)
            den += len(text)
    return num / den if den else 0.0


def drop_uncertain_numbers(contents: list[Content], stats: RetypeStats, r: Ratios = DEFAULT_RATIOS,
                           annotator: int | None = None) -> list[Content]:
    out = []
    for c in contents:
        if c.label in ("page_header", "page_footer") and c.region.label.endswith("number"):
            conf = mean_confidence(c)
            if not c.text.strip() or conf < r.page_number_min_conf:
                stats.numbers_dropped += 1
                stats.note("number dropped", f"{c.text.strip()!r} at {conf:.2f}")
                c.t.classify(annotator, c.region.id, "status", "removed", confidence=conf,
                             typography__reason="uncertain page number")
                continue
        out.append(c)
    return out


def hidden(t: Transcription, region_id: str) -> bool:
    """Whether a status puts the region nowhere (``removed``, ``suppressed``, ``duplicate`` by the default policy):
    the rule-based steps leave it out, as if it were not there."""
    status = t.status(region_id)
    return status is not None and DEFAULT_POLICY.layer(None, status=status) == "none"


def retype(t: Transcription, stats: RetypeStats | None = None, ratios: Ratios = DEFAULT_RATIOS,
           annotator: int | None = None) -> RetypeStats:
    """Apply the rules to a transcription: their decisions are added as annotations by ``annotator`` (an index into
    ``t.annotators``; ``None``: a ``retyper`` annotator is appended); returns the stats (the engine records them as
    its annotator's measurements). Regions a status puts nowhere (``hidden``) are left out."""
    if annotator is None:
        annotator = t.add_annotator(Annotator(kind="rule", step="typography", name="retyper"))
    stats = stats if stats is not None else RetypeStats()
    ranks, rows = t.region_ranks(), t.rows()
    by_region: dict[str | None, list[Line]] = {}
    for ln in t.lines:
        by_region.setdefault(t.region_of(ln), []).append(ln)
    contents = []
    for r in t.regions:
        lines = by_region.pop(r.id, [])
        if not hidden(t, r.id):
            contents.append(Content(t, r, lines, rows, t.label(r.id), ranks.get(r.id), t.heading_level(r.id)))
    unassigned = [ln for lines in by_region.values() for ln in lines]   # lines outside every region stay as they are
    body = body_size(contents)
    stats.body_size = body
    out: list[Content] = []
    for c in contents:
        head = split_leading_heading(c, body, stats, ratios, annotator) if body > 0 else None
        if head is not None:
            out.append(head)
        out.append(c)
    level_headings(out, body, stats, ratios, annotator)
    out = merge_drop_capitals(out, stats, annotator)
    out = drop_uncertain_numbers(out, stats, ratios, annotator)
    _order(t, annotator, out, unassigned, rows)
    return stats


def _order(t: Transcription, annotator: int, out: list[Content], unassigned: list[Line], rows: dict[str, int]) -> None:
    """A new reading order when the regions or lines read differently now: the ranked regions re-ranked (a headline
    just before its body region), the lines by their region's rank, then in processing order."""
    ordered = sorted((c for c in out if c.rank is not None),
                     key=lambda c: (c.rank, 0 if c.region.id.endswith("_head") else 1))
    rank = {id(c): k for k, c in enumerate(ordered)}
    reading = sorted(((c, k, ln) for c in out for k, ln in enumerate(c.lines)),
                     key=lambda x: (rank.get(id(x[0]), 1 << 30), x[1]))
    lines = [ln.id for _, _, ln in reading] + [ln.id for ln in unassigned]
    regions = [c.region.id for c in ordered]
    order = (regions, lines, [rows.get(i, 0) for i in lines])
    by_regions, by_lines = t.order("regions"), t.order("lines")
    now = (by_regions.regions if by_regions else [], by_lines.lines if by_lines else [],
           by_lines.rows if by_lines else [])
    if order != now and (regions or lines):
        t.add_order(annotator, *order)
