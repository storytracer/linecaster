"""hOCR 1.2 (XHTML) on lxml.

Mapping (see ``docs/reference/serialization.md``):

* region -> a ``div`` of class ``ocr_carea`` (``ocr_header``, ``ocr_footer``, ``ocr_photo``,
  ``ocr_table``, ``ocr_math`` for page headers, page footers, pictures/charts, tables and formulas),
  holding one ``p.ocr_par``; ``bbox`` and, when it is not the box, ``poly``;
* line -> ``span.ocr_line`` (``bbox``, ``poly``, ``baseline``, ``x_wconf``); lines without a region
  sit directly in the ``ocr_page``;
* word -> ``span.ocrx_word`` (``bbox``, ``x_wconf``), separated by spaces;
* reading order is document order;
* ``ocr-system`` is linecaster with its release, ``ocr-capabilities`` what the file contains, each step of
  ``steps`` a ``meta`` named ``linecaster-step-<n>`` (the step record as JSON), read back into ``steps``.

hOCR coordinates are integers (rounded half up, boxes by their corners) and ``x_wconf`` is an
integer percentage, so confidences round-trip to 0.01. hOCR's ``baseline`` is a straight line
(slope and offset from the box's bottom-left corner); a baseline it cannot express exactly is also
written as the custom property ``x_bline x1 y1 x2 y2 ...``. Everything else hOCR has no place for
goes into a ``data-linecaster`` JSON attribute, only when a reader would infer something else.
"""
from __future__ import annotations

import re
from typing import Any

from lxml import etree

from ..data.transcription import Line, Region, Source, StepInfo, Transcription, Word
from . import _provenance as P, _xml as X

XHTML = "http://www.w3.org/1999/xhtml"
DOCTYPE = ('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
           '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">')
EXT_ATTR = "data-linecaster"

LABEL_TO_CLASS = {
    "page_header": "ocr_header",
    "page_footer": "ocr_footer",
    "picture": "ocr_photo",
    "chart": "ocr_photo",
    "table": "ocr_table",
    "formula": "ocr_math",
}
CLASS_TO_LABEL = {
    "ocr_carea": "text",
    "ocr_header": "page_header",
    "ocr_footer": "page_footer",
    "ocr_pageno": "page_footer",
    "ocr_photo": "picture",
    "ocr_image": "picture",
    "ocr_linedrawing": "picture",
    "ocr_separator": "picture",
    "ocr_table": "table",
    "ocr_math": "formula",
    "ocr_chem": "formula",
    "ocr_float": "text",
    "ocr_textfloat": "text",
    "ocr_textimage": "picture",
    "ocr_column": "text",
}
REGION_CLASSES = set(CLASS_TO_LABEL)
LINE_CLASSES = {"ocr_line", "ocr_textfloat", "ocr_caption", "ocr_header", "ocr_footer", "ocr_pageno"}
#: ``meta`` name prefix of linecaster's step records (``linecaster-step-0``, ``-1``, ...)
STEP_META = "linecaster-step-"
#: the order of ``ocr-capabilities`` (element classes as they nest, then properties)
CAPABILITY_ORDER = ("ocr_page", "ocr_carea", "ocr_header", "ocr_footer", "ocr_photo", "ocr_table", "ocr_math",
                    "ocr_par", "ocr_line", "ocrx_word", "ocrp_lang", "ocrp_poly", "ocrp_wconf")


def _conf_pct(c: float) -> int:
    return X.round_half_up(float(c) * 100)


def quantize_confidence(c: float | None) -> float | None:
    """The confidence a reader gets back from hOCR's integer ``x_wconf``."""
    return None if c is None else _conf_pct(c) / 100


def _bbox_prop(qbox) -> str:
    x, y, w, h = qbox
    return f"bbox {int(x)} {int(y)} {int(x + w)} {int(y + h)}"


def _pts_prop(name: str, pts) -> str:
    return name + " " + " ".join(f"{int(x)} {int(y)}" for x, y in pts)


def _std_baseline(qbox, pts) -> tuple[str, list[list[float]]] | None:
    """hOCR's ``baseline slope offset`` for a polyline, and the line a reader rebuilds from it."""
    (xa, ya), (xb, yb) = pts[0], pts[-1]
    if xb == xa:
        return None
    slope = round((yb - ya) / (xb - xa), 6)
    x0, bottom = qbox[0], qbox[1] + qbox[3]
    offset = round(ya - slope * (xa - x0) - bottom, 2)
    prop = f"baseline {X.fmt_num(slope)} {X.fmt_num(offset)}"
    return prop, _baseline_from_std(qbox, slope, offset)


def _baseline_from_std(qbox, slope: float, offset: float) -> list[list[float]]:
    x0, x1, bottom = qbox[0], qbox[0] + qbox[2], qbox[1] + qbox[3]
    return [[float(x0), float(X.round_half_up(bottom + offset))],
            [float(x1), float(X.round_half_up(bottom + offset + slope * (x1 - x0)))]]


class _Writer:
    def __init__(self, t: Transcription, extensions: bool):
        self.t = t
        self.qz = X.Quantizer(0)
        self.extensions = extensions
        self.used = {r.id for r in t.regions} | {ln.id for ln in t.lines} | {
            w.id for ln in t.lines for w in ln.words}
        self.capabilities: set[str] = {"ocr_page"}   # what the file contains (``ocr-capabilities``)

    def new_id(self, base: str) -> str:
        i, cand = 0, base
        while cand in self.used:
            i += 1
            cand = f"{base}_{i}"
        self.used.add(cand)
        return cand

    def el(self, parent, tag: str, cls: str, el_id: str | None, props: list[str]) -> etree._Element:
        e = etree.SubElement(parent, f"{{{XHTML}}}{tag}")
        e.set("class", cls)
        self.capabilities.add(cls)
        if el_id is not None:
            e.set("id", el_id)
        if props:
            e.set("title", "; ".join(props))
            for prop, cap in (("poly ", "ocrp_poly"), ("x_wconf ", "ocrp_wconf")):
                if any(p.startswith(prop) for p in props):
                    self.capabilities.add(cap)
        e.text = ""
        return e

    def ext(self, e, data: dict[str, Any]) -> None:
        if data and self.extensions:
            e.set(EXT_ATTR, X.ext_dumps(data))

    def region(self, page, r: Region, lines: list[Line], predicted_ro: int) -> etree._Element:
        cls = LABEL_TO_CLASS.get(r.label, "ocr_carea")
        qbox = self.qz.box(r.bbox)
        props = [_bbox_prop(qbox)]
        qpoly = self.qz.points(r.polygon)
        if not X.same_points(qpoly, X.rect(qbox)):
            props.append(_pts_prop("poly", qpoly))
        div = self.el(page, "div", cls, r.id, props)
        ext: dict[str, Any] = {}
        if CLASS_TO_LABEL[cls] != r.label:
            ext["label"] = r.label
        if r.raw_label != cls:
            ext["raw_label"] = r.raw_label
        if r.score is not None:
            ext["score"] = r.score
        if r.heading_level is not None:
            ext["heading_level"] = r.heading_level
        if r.reading_order != predicted_ro:
            ext["reading_order"] = r.reading_order
        self.ext(div, ext)
        par = self.el(div, "p", "ocr_par", self.new_id(f"{r.id}_par"), [_bbox_prop(qbox)])
        return par

    def line(self, parent, ln: Line, pos) -> None:
        qbox = self.qz.box(ln.bbox)
        props = [_bbox_prop(qbox)]
        ext = X.line_order_ext(ln, pos)
        if ln.baseline:
            qbl = self.qz.points(ln.baseline)
            std = _std_baseline(qbox, qbl) if len(qbl) >= 2 else None
            if std is not None:
                props.append(std[0])
            if std is None or not X.same_points(std[1], qbl):
                props.append(_pts_prop("x_bline", qbl))
        if ln.polygon:
            props.append(_pts_prop("poly", self.qz.points(ln.polygon)))
        if ln.confidence is not None:
            props.append(f"x_wconf {_conf_pct(ln.confidence)}")
        span = self.el(parent, "span", "ocr_line", ln.id, props)
        if ln.score is not None:
            ext["score"] = ln.score
        if ln.words:
            prev = None
            for w in ln.words:
                if prev is not None:
                    prev.tail = " "
                wprops = []
                if w.bbox is not None:
                    wprops.append(_bbox_prop(self.qz.box(w.bbox)))
                if w.confidence is not None:
                    wprops.append(f"x_wconf {_conf_pct(w.confidence)}")
                ws = self.el(span, "span", "ocrx_word", w.id, wprops)
                ws.text = w.text
                wext: dict[str, Any] = {}
                if w.hyphen:
                    wext["hyphen"] = True
                if w.alternatives:
                    wext["alternatives"] = w.alternatives
                self.ext(ws, wext)
                prev = ws
            if ln.text != X.joined_words(ln):
                ext["text"] = ln.text
        else:
            span.text = ln.text or ""
            if ln.text is None:
                ext["text"] = None
        if ln.alternatives:
            ext["alternatives"] = ln.alternatives
        self.ext(span, ext)

    def write(self, width: int, height: int, uri: str | None, language: str | None) -> bytes:
        t = self.t
        units = X.units_in_order(t)
        pos = X.line_positions(units)
        real = [u.region for u in units if not u.synthetic]
        ranks = {r.id: i for i, r in enumerate(real)}

        html = etree.Element(f"{{{XHTML}}}html", nsmap={None: XHTML})
        if language:
            html.set("lang", language)
            html.set("{http://www.w3.org/XML/1998/namespace}lang", language)
        head = etree.SubElement(html, f"{{{XHTML}}}head")
        etree.SubElement(head, f"{{{XHTML}}}title").text = ""

        def meta(name: str, content: str) -> etree._Element:
            m = etree.SubElement(head, f"{{{XHTML}}}meta")
            m.set("name", name)
            m.set("content", content)
            return m

        meta("ocr-system", P.software())
        capabilities = meta("ocr-capabilities", "")     # filled in once the page is written
        meta("ocr-number-of-pages", "1")
        if language and re.fullmatch(r"[a-z]{2}", language):     # hOCR names ISO 639-1 codes
            meta("ocr-langs", language)
        for i, m in enumerate(t.steps):
            meta(f"{STEP_META}{i}", P.dumps(P.record(m)))
        if language:
            self.capabilities.add("ocrp_lang")
        body = etree.SubElement(html, f"{{{XHTML}}}body")
        props = []
        if uri:
            props.append(f'image "{uri}"')
        props += [f"bbox 0 0 {width} {height}", "ppageno 0"]
        page = self.el(body, "div", "ocr_page", self.new_id("page_1"), props)
        for u in units:
            if u.synthetic:
                parent = page
            else:
                parent = self.region(page, u.region, u.lines, ranks[u.region.id])
            for ln in u.lines:
                self.line(parent, ln, pos)
        capabilities.set("content", " ".join(c for c in CAPABILITY_ORDER if c in self.capabilities))
        return etree.tostring(html, xml_declaration=True, encoding="UTF-8", doctype=DOCTYPE,
                              pretty_print=True)


def to_hocr(t: Transcription, *, image_width: int | None = None, image_height: int | None = None,
            image_uri: str | None = None, extensions: bool = True) -> bytes:
    """Serialize ``t`` as hOCR 1.2 (XHTML, UTF-8)."""
    width = image_width if image_width is not None else t.source.image_width
    height = image_height if image_height is not None else t.source.image_height
    if width is None or height is None:
        raise ValueError("to_hocr needs the image size (image_width/image_height or t.source)")
    uri = image_uri if image_uri is not None else t.source.uri
    return _Writer(t, extensions).write(int(width), int(height), uri, t.language)


# ================================================================ reading

_PROP = re.compile(r'\s*([A-Za-z_][\w]*)\s*((?:"[^"]*"|[^;"])*)')


def parse_title(title: str | None) -> dict[str, str]:
    """Split an hOCR ``title`` into properties (values may be quoted and contain ``;``)."""
    out: dict[str, str] = {}
    if not title:
        return out
    for m in _PROP.finditer(title):
        name, value = m.group(1), m.group(2).strip()
        out.setdefault(name, value)
    return out


def _nums(v: str | None) -> list[float]:
    if not v:
        return []
    try:
        return [float(n) for n in v.split()]
    except ValueError:
        return []


def _bbox(props) -> list[float] | None:
    n = _nums(props.get("bbox"))
    if len(n) != 4:
        return None
    return [n[0], n[1], n[2] - n[0], n[3] - n[1]]


def _pairs(v: str | None) -> list[list[float]] | None:
    n = _nums(v)
    if len(n) < 2 or len(n) % 2:
        return None
    return [[n[i], n[i + 1]] for i in range(0, len(n), 2)]


def _classes(el) -> set[str]:
    return set((el.get("class") or "").split())


def _parse(data: bytes | str):
    try:
        return X.parse_xml(data)
    except etree.XMLSyntaxError:
        import lxml.html
        root = lxml.html.fromstring(data if isinstance(data, bytes) else data.encode("utf-8"))
        return X.parse_xml(root)


def from_hocr(data: bytes | str, *, uri: str | None = None, page: int = 0) -> Transcription:
    """Read hOCR (XHTML or tag-soup HTML; Tesseract, OCRopus, kraken, ...). ``page`` picks the
    ``ocr_page`` of a multi-page file."""
    root, _ = _parse(data)
    pages = [el for el in root.iter() if isinstance(el.tag, str) and "ocr_page" in _classes(el)]
    t = Transcription()
    if not pages:
        t.source = Source(kind="converted", format="hocr", uri=uri)
        return t
    pg = pages[page]
    pprops = parse_title(pg.get("title"))
    state = {"line": 0, "region": 0, "orphan_row": 0, "gen": 0}
    _walk(pg, t, state, None)
    pbox = _bbox(pprops)
    image = pprops.get("image", "").strip().strip('"') or None
    t.language = root.get("lang") or None
    t.steps = _steps(root)
    t.source = Source(kind="converted", format="hocr", uri=uri or image,
                      image_width=int(pbox[2]) if pbox else None,
                      image_height=int(pbox[3]) if pbox else None)
    return t


def _steps(root) -> list[StepInfo]:
    """linecaster's step records from the ``linecaster-step-<n>`` metas, in ``n`` order; for a foreign file,
    the software named by ``ocr-system`` as one ``page`` step."""
    metas = {}
    for m in root.iter("meta"):
        name, content = m.get("name") or "", m.get("content")
        if content is not None:
            metas.setdefault(name, content)
    steps = sorted(((int(k[len(STEP_META):]), v) for k, v in metas.items()
                    if k.startswith(STEP_META) and k[len(STEP_META):].isdigit()), key=lambda kv: kv[0])
    if steps:
        return [P.from_record(X.ext_loads(v)) for _, v in steps]
    system = (metas.get("ocr-system") or "").strip()
    if system and not system.startswith(P.SOFTWARE):
        return [StepInfo(step="recognition", name=system)]
    return []


def _has_line_descendant(el) -> bool:
    for d in el.iterdescendants():
        if isinstance(d.tag, str) and _classes(d) & LINE_CLASSES:
            return True
    return False


def _walk(el, t: Transcription, state, region: Region | None) -> None:
    for c in el:
        if not isinstance(c.tag, str):
            continue
        cls = _classes(c)
        # ocr_header/ocr_footer/ocr_textfloat are line classes inside a region (Tesseract) and
        # region classes at page level: a page-level one is a line only as a span without lines
        if cls & LINE_CLASSES and (region is not None or not (cls & REGION_CLASSES)
                                   or (c.tag == "span" and not _has_line_descendant(c))):
            _line(c, t, state, region)
        elif region is None and cls & REGION_CLASSES:
            r = _region(c, cls, t, state)
            state["region_row"] = 0
            _walk(c, t, state, r)
            state["orphan_row"] = 0
        else:
            _walk(c, t, state, region)


def _ext(el) -> dict[str, Any]:
    return X.ext_loads(el.get(EXT_ATTR))


def _region(el, cls: set[str], t: Transcription, state) -> Region:
    props = parse_title(el.get("title"))
    ext = _ext(el)
    primary = next((c for c in el.get("class", "").split() if c in REGION_CLASSES), "ocr_carea")
    rid = el.get("id")
    if not rid:
        state["gen"] += 1
        rid = f"block_{state['gen']}"
    poly = _pairs(props.get("poly"))
    bbox = _bbox(props) or (X.bounds(poly) if poly else [0.0, 0.0, 0.0, 0.0])
    r = Region(id=rid, label=ext.get("label", CLASS_TO_LABEL.get(primary, "text")),
               raw_label=ext.get("raw_label", primary), polygon=poly or X.rect(bbox), bbox=bbox,
               score=ext.get("score"), heading_level=ext.get("heading_level"),
               reading_order=ext.get("reading_order", state["region"]))
    state["region"] += 1
    t.regions.append(r)
    return r


def _line(el, t: Transcription, state, region: Region | None) -> None:
    props = parse_title(el.get("title"))
    ext = _ext(el)
    rank = state["line"]
    state["line"] += 1
    if region is None:
        row = state["orphan_row"]
        state["orphan_row"] += 1
    else:
        row = state.get("region_row", 0)
        state["region_row"] = row + 1
    lid = el.get("id") or f"line_{rank}"
    words: list[Word] = []
    for k, we in enumerate(d for d in el.iter() if isinstance(d.tag, str) and "ocrx_word" in _classes(d)):
        wp = parse_title(we.get("title"))
        wext = _ext(we)
        conf = wp.get("x_wconf")
        words.append(Word(id=we.get("id") or f"{lid}_w{k}", text="".join(we.itertext()), bbox=_bbox(wp),
                          confidence=float(conf) / 100 if conf and _nums(conf) else None,
                          hyphen=bool(wext.get("hyphen")), alternatives=wext.get("alternatives", [])))
    poly = _pairs(props.get("poly"))
    bbox = _bbox(props) or (X.bounds(poly) if poly else [0.0, 0.0, 0.0, 0.0])
    baseline = _pairs(props.get("x_bline"))
    if baseline is None and props.get("baseline"):
        n = _nums(props["baseline"])
        if len(n) == 2:
            baseline = _baseline_from_std(bbox, n[0], n[1])
    if words:
        text = " ".join(w.text for w in words)
    else:
        text = "".join(el.itertext())
    if "text" in ext:
        text = ext["text"]
    conf = props.get("x_wconf")
    t.lines.append(Line(
        id=lid, region_id=region.id if region is not None else None,
        reading_order=ext.get("reading_order", rank), row=ext.get("row", row), bbox=bbox, polygon=poly,
        baseline=baseline, score=ext.get("score"), text=text,
        confidence=float(conf) / 100 if conf and _nums(conf) else None,
        alternatives=ext.get("alternatives", []), words=words,
    ))
