"""Shared helpers for the ALTO, PAGE-XML and hOCR serialisers (lxml only, no engines).

Every writer follows the same rule: a value goes into the format's own vocabulary when the format
has a place for it; what the format cannot hold, or what a reader would infer differently, goes into
a small JSON *extension* attached to the element (ALTO: an ``OtherTag`` of ``TYPE="linecaster"``
referenced by ``TAGREFS``; PAGE: ``UserDefined/UserAttribute[@name="linecaster"]``; hOCR: a
``data-linecaster`` attribute). Writers compute what their reader would infer and only write the
extension when it differs, so a typical page carries few or none. Readers of foreign files never
see an extension and use the inferred values.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Iterable, Sequence

from lxml import etree

from .model import Line, Region, Transcription

EXT_KEY = "linecaster"

# ---------------------------------------------------------------- numbers and geometry


def round_half_up(v: float) -> int:
    """Round to the nearest integer, halves away from minus infinity (deterministic, unlike ``round``)."""
    return int(math.floor(v + 0.5))


def fmt_num(v: float, precision: int | None = None) -> str:
    """Format a coordinate: integral values without a decimal point; ``precision=None`` keeps the
    shortest representation that reads back to the same float (exact), an int rounds to that many
    decimals (0 = integers, half up)."""
    v = float(v)
    if precision is not None:
        if precision <= 0:
            return str(round_half_up(v))
        v = round(v, precision)
    if v.is_integer():
        return str(int(v))
    return repr(v)


def parse_num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def round_bbox(bbox: Sequence[float]) -> list[float]:
    """Round a ``[x, y, w, h]`` box by its corners, so the edges land on the same integers as the
    rounded edges of neighbouring geometry."""
    x0, y0 = round_half_up(bbox[0]), round_half_up(bbox[1])
    x1, y1 = round_half_up(bbox[0] + bbox[2]), round_half_up(bbox[1] + bbox[3])
    return [float(x0), float(y0), float(x1 - x0), float(y1 - y0)]


def round_points(points: Sequence[Sequence[float]], clamp: bool = False) -> list[list[float]]:
    out = []
    for x, y in points:
        xi, yi = round_half_up(x), round_half_up(y)
        if clamp:
            xi, yi = max(xi, 0), max(yi, 0)
        out.append([float(xi), float(yi)])
    return out


def bounds(points: Sequence[Sequence[float]]) -> list[float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def rect(bbox: Sequence[float]) -> list[list[float]]:
    x, y, w, h = (float(v) for v in bbox)
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def fmt_points(points: Sequence[Sequence[float]], precision: int | None = None, sep: str = ",") -> str:
    return " ".join(f"{fmt_num(x, precision)}{sep}{fmt_num(y, precision)}" for x, y in points)


def parse_points(s: str | None) -> list[list[float]] | None:
    """Parse ``"x1,y1 x2,y2"`` or ``"x1 y1 x2 y2"`` (both occur in ALTO and PAGE files)."""
    if not s or not s.strip():
        return None
    nums = re.split(r"[\s,]+", s.strip())
    try:
        vals = [float(n) for n in nums if n]
    except ValueError:
        return None
    if len(vals) < 2 or len(vals) % 2:
        return None
    return [[vals[i], vals[i + 1]] for i in range(0, len(vals), 2)]


def same_points(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return len(a) == len(b) and all(float(p[0]) == float(q[0]) and float(p[1]) == float(q[1])
                                    for p, q in zip(a, b))


def same_box(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return len(a) == len(b) and all(float(p) == float(q) for p, q in zip(a, b))


# ---------------------------------------------------------------- extension payloads


def ext_dumps(d: dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def ext_loads(s: str | None) -> dict[str, Any]:
    if not s:
        return {}
    try:
        d = json.loads(s)
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


# ---------------------------------------------------------------- XML


def parse_xml(data: bytes | str | etree._Element) -> tuple[etree._Element, str | None]:
    """Parse XML bytes or text safely (no network, no entity expansion) and strip namespaces, so
    readers handle every schema version, with or without namespace, with the same code. Returns the
    root and the root's original namespace (None without one)."""
    if isinstance(data, etree._Element):
        root = data
    else:
        if isinstance(data, str):
            data = data.encode("utf-8")
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True,
                                 remove_comments=True, remove_pis=True)
        root = etree.fromstring(data, parser)
    ns = etree.QName(root).namespace
    strip_namespaces(root)
    return root, ns


def strip_namespaces(root: etree._Element) -> None:
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        el.tag = etree.QName(el).localname
        for k in list(el.attrib):
            if k.startswith("{"):
                local = etree.QName(k).localname
                v = el.attrib.pop(k)
                if local not in el.attrib:
                    el.set(local, v)
    etree.cleanup_namespaces(root)


def ncname(s: str) -> str:
    """Make ``s`` usable as an XML ID (an NCName): invalid characters become ``_``, a leading
    non-letter gets a ``_`` prefix."""
    s = re.sub(r"[^A-Za-z0-9_.\-]", "_", s)
    if not s or not (s[0].isalpha() or s[0] == "_"):
        s = "_" + s
    return s


class Quantiser:
    """Coordinate precision of a writer and what its reader will get back.

    ``precision=None`` writes floats exactly (shortest repr), ``0`` writes integers (half up), ``k``
    rounds to ``k`` decimals. Boxes are rounded by their corners."""

    def __init__(self, precision: int | None, clamp: bool = False):
        self.precision = precision
        self.clamp = clamp

    def q(self, v: float) -> float:
        p = self.precision
        if p is None:
            return float(v)
        v = float(round_half_up(v)) if p <= 0 else round(float(v), p)
        if self.clamp and v < 0:
            v = 0.0
        return v

    def box(self, b: Sequence[float]) -> list[float]:
        """The box as written and read back: ``[x, y, w, h]``."""
        if self.precision is None:
            return [float(v) for v in b]
        x0, y0 = self.q(b[0]), self.q(b[1])
        x1, y1 = self.q(b[0] + b[2]), self.q(b[1] + b[3])
        w, h = x1 - x0, y1 - y0
        if self.precision > 0:
            w, h = round(w, self.precision), round(h, self.precision)
        return [x0, y0, w, h]

    def points(self, pts: Sequence[Sequence[float]] | None) -> list[list[float]] | None:
        if pts is None:
            return None
        return [[self.q(x), self.q(y)] for x, y in pts]

    def num(self, v: float) -> str:
        return fmt_num(v, None if self.precision is None else self.precision)

    def fmt_points(self, pts: Sequence[Sequence[float]], sep: str = ",") -> str:
        return " ".join(f"{self.num(x)}{sep}{self.num(y)}" for x, y in self.points(pts))


def children(el: etree._Element, *names: str) -> list[etree._Element]:
    return [c for c in el if isinstance(c.tag, str) and c.tag in names]


def child(el: etree._Element, name: str) -> etree._Element | None:
    for c in el:
        if isinstance(c.tag, str) and c.tag == name:
            return c
    return None


# ---------------------------------------------------------------- labels

#: Docling label -> PAGE TextRegion/@type (text-bearing regions)
DOCLING_TO_PAGE_TEXT = {
    "text": "paragraph",
    "paragraph": "paragraph",
    "title": "heading",
    "section_header": "heading",
    "page_header": "header",
    "page_footer": "footer",
    "caption": "caption",
    "footnote": "footnote",
    "list_item": "paragraph",
    "document_index": "TOC-entry",
    "handwritten_text": "paragraph",
    "reference": "paragraph",
    "code": "other",
    "formula": "other",
    "table": "other",
    "picture": "other",
    "chart": "other",
}

#: Docling label -> PAGE region element for regions without lines
DOCLING_TO_PAGE_ELEMENT = {
    "picture": "ImageRegion",
    "chart": "ChartRegion",
    "table": "TableRegion",
    "formula": "MathsRegion",
}

#: PAGE region element (other than TextRegion) -> Docling label
PAGE_ELEMENT_TO_DOCLING = {
    "ImageRegion": "picture",
    "LineDrawingRegion": "picture",
    "GraphicRegion": "picture",
    "ChartRegion": "chart",
    "MapRegion": "picture",
    "TableRegion": "table",
    "MathsRegion": "formula",
    "ChemRegion": "formula",
    "MusicRegion": "picture",
    "AdvertRegion": "picture",
    "SeparatorRegion": "picture",
    "NoiseRegion": "picture",
    "UnknownRegion": "text",
    "CustomRegion": "text",
}

#: Region labels as other tools name them (PAGE text types, Transkribus/eScriptorium structure
#: types, ALTO tags, PP-DocLayout names), lower-cased -> Docling label. Unknown names map to "text".
RAW_TO_DOCLING = {
    # PAGE TextRegion/@type
    "paragraph": "text",
    "heading": "section_header",
    "caption": "caption",
    "header": "page_header",
    "footer": "page_footer",
    "page-number": "page_footer",
    "drop-capital": "text",
    "credit": "text",
    "floating": "text",
    "signature-mark": "page_footer",
    "catch-word": "page_footer",
    "marginalia": "text",
    "footnote": "footnote",
    "footnote-continued": "footnote",
    "endnote": "footnote",
    "toc-entry": "document_index",
    "list-label": "list_item",
    "other": "text",
    # Docling's own names
    "text": "text",
    "title": "title",
    "section_header": "section_header",
    "page_header": "page_header",
    "page_footer": "page_footer",
    "list_item": "list_item",
    "picture": "picture",
    "table": "table",
    "formula": "formula",
    "chart": "chart",
    "code": "code",
    "document_index": "document_index",
    "handwritten_text": "handwritten_text",
    "reference": "reference",
    # eScriptorium / SegmOnto-style names
    "main": "text",
    "maintext": "text",
    "maintextzone": "text",
    "marginaltextzone": "text",
    "numberingzone": "page_header",
    "runningtitlezone": "page_header",
    "titlepagezone": "title",
    "quirezone": "page_footer",
    "graphiczone": "picture",
    "tablezone": "table",
    "musiczone": "picture",
    "dropcapitalzone": "text",
    # PP-DocLayout names
    "doc_title": "title",
    "paragraph_title": "section_header",
    "number": "page_footer",
    "header_image": "picture",
    "footer_image": "picture",
    "image": "picture",
    "figure": "picture",
    "figure_title": "caption",
    "table_title": "caption",
    "chart_title": "caption",
    "display_formula": "formula",
    "inline_formula": "formula",
    "formula_number": "text",
    "abstract": "text",
    "content": "document_index",
    "aside_text": "text",
    "vertical_text": "text",
    "algorithm": "code",
    "seal": "picture",
    "vision_footnote": "footnote",
}


def docling_from_raw(raw: str | None, default: str = "text") -> str:
    if not raw:
        return default
    key = raw.strip().lower()
    return RAW_TO_DOCLING.get(key, RAW_TO_DOCLING.get(key.replace(" ", "-"), default))


# ---------------------------------------------------------------- units and order


class Unit:
    """One top-level block a writer emits: a region with its lines, or a run of lines without a
    region (written as a synthetic block the reader drops again)."""

    __slots__ = ("region", "lines", "block_id")

    def __init__(self, region: Region | None, lines: list[Line], block_id: str):
        self.region = region
        self.lines = lines
        self.block_id = block_id

    @property
    def synthetic(self) -> bool:
        return self.region is None


def units_in_order(t: Transcription) -> list[Unit]:
    """The order in which writers emit blocks.

    Regions are sorted by ``reading_order`` (regions without one after those with one, in list
    order); each region's lines by ``reading_order``. Lines without a (known) region are placed
    before the first region whose first line comes after them; consecutive ones share one synthetic
    block. Line ``reading_order`` round-trips exactly when this document order reproduces it
    (otherwise the writers record it in the extension).
    """
    region_ids = {r.id for r in t.regions}
    by_region: dict[str, list[Line]] = {}
    orphans: list[Line] = []
    for ln in t.lines:
        if ln.region_id is not None and ln.region_id in region_ids:
            by_region.setdefault(ln.region_id, []).append(ln)
        else:
            orphans.append(ln)
    idx = {id(r): i for i, r in enumerate(t.regions)}
    regions = sorted(t.regions, key=lambda r: (r.reading_order is None, r.reading_order or 0, idx[id(r)]))
    seq: list[tuple[Region | None, list[Line]]] = []
    for r in regions:
        seq.append((r, sorted(by_region.get(r.id, []), key=lambda ln: ln.reading_order)))
    oidx = {id(ln): i for i, ln in enumerate(orphans)}
    orphans.sort(key=lambda ln: (ln.reading_order, oidx[id(ln)]))
    for ln in orphans:
        pos = len(seq)
        for i, (r, lns) in enumerate(seq):
            if r is not None and lns and lns[0].reading_order > ln.reading_order:
                pos = i
                break
        # join an adjacent synthetic run
        if pos > 0 and seq[pos - 1][0] is None and (pos == len(seq) or seq[pos][0] is not None):
            seq[pos - 1][1].append(ln)
        else:
            seq.insert(pos, (None, [ln]))
    used = {r.id for r in t.regions} | {ln.id for ln in t.lines} | {w.id for ln in t.lines for w in ln.words}
    units, k = [], 0
    for r, lns in seq:
        if r is not None:
            units.append(Unit(r, lns, r.id))
        else:
            while f"lc_block_{k}" in used:
                k += 1
            bid = f"lc_block_{k}"
            used.add(bid)
            units.append(Unit(None, lns, bid))
    return units


def unit_bbox(lines: Iterable[Line]) -> list[float]:
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for ln in lines:
        x, y, w, h = ln.bbox
        x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x + w), max(y1, y + h)
    return [x0, y0, x1 - x0, y1 - y0]


def region_ranks(units: list[Unit]) -> dict[str, int]:
    """The reading order a reader infers for the real regions with an order: their rank among them."""
    ordered = [u.region for u in units if u.region is not None and u.region.reading_order is not None]
    return {r.id: i for i, r in enumerate(ordered)}


def line_positions(units: list[Unit]) -> dict[str, tuple[int, int]]:
    """``line id -> (page rank, row in its block)`` as a reader infers them from document order."""
    out, n = {}, 0
    for u in units:
        for row, ln in enumerate(u.lines):
            out[ln.id] = (n, row)
            n += 1
    return out


def line_order_ext(ln: Line, pos: dict[str, tuple[int, int]]) -> dict[str, Any]:
    rank, row = pos[ln.id]
    ext: dict[str, Any] = {}
    if ln.reading_order != rank:
        ext["reading_order"] = ln.reading_order
    if ln.row != row:
        ext["row"] = ln.row
    return ext


def joined_words(ln: Line) -> str:
    return " ".join(w.text for w in ln.words)


def mean_confidence(items: Iterable[tuple[str, float | None]]) -> float | None:
    """Length-weighted mean of (text, confidence) pairs; None when no item has a confidence."""
    num = den = 0.0
    for text, c in items:
        if c is None:
            continue
        n = max(len(text), 1)
        num += c * n
        den += n
    return num / den if den else None
