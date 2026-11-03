"""ALTO (writes v4.4; reads v1 to v4, with or without namespace) on lxml.

Mapping (see ``specs/serialisation.md``):

* region -> ``TextBlock`` (``Illustration`` for a picture or chart region without lines), its
  Docling label as a ``LayoutTag`` of ``TYPE="label"``, its producer's label as a ``LayoutTag`` of
  ``TYPE="raw_label"``; region reading order -> ``ReadingOrder/OrderedGroup/ElementRef``;
* line -> ``TextLine`` (``BASELINE`` as a points list, polygon as ``Shape/Polygon``);
* word -> ``String`` (``WC`` 0..1, ``ALTERNATIVE``), ``SP`` between words, a line-end hyphen as
  ``HYP``; a line without words is written as one ``String`` carrying the line's text;
* lines without a region go into a synthetic ``TextBlock`` the reader drops again.

What ALTO has no place for (line confidence, detection scores, heading level, ...) goes into a
per-element extension, only when a reader would infer something else (see ``_xml``).
"""
from __future__ import annotations

from typing import Any

from lxml import etree

from . import _xml as X
from .model import Line, Region, Source, Transcription, Word

NS = "http://www.loc.gov/standards/alto/ns-v4#"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XLINK = "http://www.w3.org/1999/xlink"
SCHEMA_LOCATION = f"{NS} http://www.loc.gov/standards/alto/v4/alto-4-4.xsd"
HYPHENS = ("-", "¬", "⸗", "‐", "­", "=")
ILLUSTRATION_LABELS = ("picture", "chart")


def _e(parent, tag: str, **attrs) -> etree._Element:
    el = etree.SubElement(parent, f"{{{NS}}}{tag}")
    for k, v in attrs.items():
        if v is not None:
            el.set(k, str(v))
    return el


class _Writer:
    def __init__(self, t: Transcription, precision: int | None, extensions: bool):
        self.t = t
        self.qz = X.Quantiser(precision)
        self.extensions = extensions
        self.used: set[str] = {r.id for r in t.regions} | {ln.id for ln in t.lines} | {
            w.id for ln in t.lines for w in ln.words}
        self.tags: list[tuple[str, str, str, str, str | None]] = []   # (element, id, type, label, description)
        self.tag_ids: dict[tuple[str, str], str] = {}

    def new_id(self, base: str) -> str:
        base = X.ncname(base)
        i, cand = 0, base
        while cand in self.used:
            i += 1
            cand = f"{base}_{i}"
        self.used.add(cand)
        return cand

    def tag(self, kind: str, label: str) -> str:
        key = (kind, label)
        if key not in self.tag_ids:
            tid = self.new_id(f"lc_{kind}_{label}")
            self.tag_ids[key] = tid
            self.tags.append(("LayoutTag", tid, kind, label, None))
        return self.tag_ids[key]

    def ext(self, el: etree._Element, element_id: str, data: dict[str, Any]) -> None:
        if not data or not self.extensions:
            return
        tid = self.new_id(f"lcx_{element_id}")
        self.tags.append(("OtherTag", tid, X.EXT_KEY, X.EXT_KEY, X.ext_dumps(data)))
        refs = el.get("TAGREFS")
        el.set("TAGREFS", f"{refs} {tid}" if refs else tid)

    def box(self, el: etree._Element, bbox) -> None:
        x, y, w, h = self.qz.box(bbox)
        el.set("HPOS", self.qz.num(x))
        el.set("VPOS", self.qz.num(y))
        el.set("WIDTH", self.qz.num(w))
        el.set("HEIGHT", self.qz.num(h))

    def shape(self, el: etree._Element, points) -> None:
        sh = _e(el, "Shape")
        _e(sh, "Polygon", POINTS=self.qz.fmt_points(points))

    # ------------------------------------------------------------ blocks
    def region_block(self, parent, r: Region, lines: list[Line], predicted_ro: int | None) -> etree._Element:
        tag = "Illustration" if (not lines and r.label in ILLUSTRATION_LABELS) else "TextBlock"
        el = _e(parent, tag, ID=r.id)
        if tag == "Illustration":
            el.set("TYPE", r.label)
        self.box(el, r.bbox)
        refs = [self.tag("label", r.label)]
        if r.raw_label:
            refs.append(self.tag("raw_label", r.raw_label))
        el.set("TAGREFS", " ".join(refs))
        if not X.same_points(self.qz.points(r.polygon), X.rect(self.qz.box(r.bbox))):
            self.shape(el, r.polygon)
        ext: dict[str, Any] = {}
        if r.score is not None:
            ext["score"] = r.score
        if r.heading_level is not None:
            ext["heading_level"] = r.heading_level
        if r.reading_order != predicted_ro:
            ext["reading_order"] = r.reading_order
        self.ext(el, r.id, ext)
        return el

    def text_line(self, block, ln: Line, pos) -> None:
        el = _e(block, "TextLine", ID=ln.id)
        self.box(el, ln.bbox)
        if ln.baseline:
            el.set("BASELINE", self.qz.fmt_points(ln.baseline))
        if ln.polygon:
            self.shape(el, ln.polygon)
        ext = X.line_order_ext(ln, pos)
        if ln.score is not None:
            ext["score"] = ln.score
        if ln.words:
            hyphen_extra = []
            last = len(ln.words) - 1
            hyp = None
            for i, w in enumerate(ln.words):
                text = w.text
                if w.hyphen:
                    if i == last and len(text) > 1 and text.endswith(HYPHENS):
                        text, hyp = text[:-1], text[-1]
                    else:
                        hyphen_extra.append(w.id)
                if i:
                    _e(el, "SP")
                self.string(el, w, text)
            if hyp is not None:
                _e(el, "HYP", CONTENT=hyp)
            if hyphen_extra:
                ext["hyphen"] = hyphen_extra
            if ln.text != X.joined_words(ln):
                ext["text"] = ln.text
            predicted_conf = X.mean_confidence((w.text, w.confidence) for w in ln.words)
            if ln.confidence != predicted_conf:
                ext["confidence"] = ln.confidence
        else:
            s = _e(el, "String", CONTENT=ln.text or "")
            self.box(s, ln.bbox)
            if ln.confidence is not None:
                s.set("WC", repr(float(ln.confidence)))
            ext["wordless"] = True
            if ln.text is None:
                ext["text"] = None
        if ln.alternatives:
            ext["alternatives"] = ln.alternatives
        self.ext(el, ln.id, ext)

    def string(self, line_el, w: Word, text: str) -> None:
        s = _e(line_el, "String", ID=w.id, CONTENT=text)
        if w.bbox is not None:
            self.box(s, w.bbox)
        if w.confidence is not None:
            s.set("WC", repr(float(w.confidence)))
        for alt in w.alternatives:
            a = _e(s, "ALTERNATIVE")
            a.text = alt

    # ------------------------------------------------------------ document
    def write(self, width: int, height: int, uri: str | None) -> bytes:
        t = self.t
        units = X.units_in_order(t)
        for u in units:
            self.used.add(u.block_id)
        in_group = [u for u in units if u.synthetic or u.region.reading_order is not None]
        if in_group:
            ranks = X.region_ranks(units)
        else:   # no ReadingOrder element: a reader takes document order
            ranks = {u.region.id: i for i, u in enumerate(units)}
        pos = X.line_positions(units)

        root = etree.Element(f"{{{NS}}}alto", nsmap={None: NS, "xsi": XSI, "xlink": XLINK})
        root.set(f"{{{XSI}}}schemaLocation", SCHEMA_LOCATION)
        root.set("SCHEMAVERSION", "4.4")
        desc = _e(root, "Description")
        _e(desc, "MeasurementUnit").text = "pixel"
        if uri:
            sii = _e(desc, "sourceImageInformation")
            _e(sii, "fileName").text = uri
        for i, m in enumerate(t.model):
            p = _e(desc, "Processing", ID=self.new_id(f"lc_processing_{i}"))
            _e(p, "processingStepDescription").text = m.step
            if m.settings:
                _e(p, "processingStepSettings").text = X.ext_dumps(m.settings)
            sw = _e(p, "processingSoftware")
            _e(sw, "softwareName").text = m.name
            if m.revision:
                _e(sw, "softwareVersion").text = m.revision

        layout = etree.Element(f"{{{NS}}}Layout")
        page = _e(layout, "Page", ID=self.new_id("page_1"), PHYSICAL_IMG_NR="1",
                  WIDTH=str(width), HEIGHT=str(height))
        ps = _e(page, "PrintSpace", HPOS="0", VPOS="0", WIDTH=str(width), HEIGHT=str(height))
        for u in units:
            if u.synthetic:
                block = _e(ps, "TextBlock", ID=u.block_id)
                self.box(block, X.unit_bbox(u.lines))
                block.set("TAGREFS", self.tag("label", "text"))
                self.ext(block, u.block_id, {"synthetic": True})
            else:
                block = self.region_block(ps, u.region, u.lines, ranks.get(u.region.id))
            for ln in u.lines:
                self.text_line(block, ln, pos)

        if self.tags:
            tags = _e(root, "Tags")
            for element, tid, kind, label, description in self.tags:
                _e(tags, element, ID=tid, TYPE=kind, LABEL=label, DESCRIPTION=description)
        if in_group:
            ro = _e(root, "ReadingOrder")
            grp = _e(ro, "OrderedGroup", ID=self.new_id("lc_reading_order"))
            for u in in_group:
                _e(grp, "ElementRef", ID=self.new_id(f"lc_ro_{u.block_id}"), REF=u.block_id)
        root.append(layout)
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def to_alto(t: Transcription, *, image_width: int | None = None, image_height: int | None = None,
            image_uri: str | None = None, precision: int | None = None, extensions: bool = True) -> bytes:
    """Serialise ``t`` as ALTO 4.4 (pixel units).

    ``image_width``/``image_height`` default to ``t.source``'s. ``precision``: ``None`` writes
    coordinates exactly as stored (ALTO coordinates are floats), ``0`` writes integers (rounded half
    up; boxes by their corners). ``extensions=False`` leaves out the linecaster extension tags
    (the file then only round-trips what ALTO itself holds).
    """
    width = image_width if image_width is not None else t.source.image_width
    height = image_height if image_height is not None else t.source.image_height
    if width is None or height is None:
        raise ValueError("to_alto needs the image size (image_width/image_height or t.source)")
    uri = image_uri if image_uri is not None else t.source.uri
    return _Writer(t, precision, extensions).write(int(width), int(height), uri)


# ================================================================ reading


class _Scale:
    def __init__(self, sx: float, sy: float):
        self.sx, self.sy = sx, sy
        self.identity = sx == 1.0 and sy == 1.0

    def box(self, el) -> list[float] | None:
        vals = [X.parse_num(el.get(k)) for k in ("HPOS", "VPOS", "WIDTH", "HEIGHT")]
        if any(v is None for v in vals):
            return None
        x, y, w, h = vals
        if self.identity:
            return [x, y, w, h]
        return [x * self.sx, y * self.sy, w * self.sx, h * self.sy]

    def points(self, pts):
        if pts is None or self.identity:
            return pts
        return [[x * self.sx, y * self.sy] for x, y in pts]

    def y(self, v: float) -> float:
        return v if self.identity else v * self.sy


def _scale_for(unit: str, page_w, page_h, image_width, image_height, dpi) -> _Scale:
    if image_width and image_height and page_w and page_h:
        return _Scale(image_width / page_w, image_height / page_h)
    if unit == "pixel":
        return _Scale(1.0, 1.0)
    if dpi:
        f = dpi / 254.0 if unit == "mm10" else dpi / 1200.0
        return _Scale(f, f)
    raise ValueError(f"ALTO MeasurementUnit {unit!r} needs the image size (with Page WIDTH/HEIGHT "
                     "present) or the scan resolution (dpi) to convert to pixels")


def _reading_order_refs(ro) -> list[str]:
    refs: list[str] = []
    for el in ro.iter():
        if el.tag == "ElementRef" or (el.tag in ("OrderedGroup", "UnorderedGroup") and el.get("REF")):
            refs.extend((el.get("REF") or "").split())
    return refs


def from_alto(data: bytes | str, *, image_width: int | None = None, image_height: int | None = None,
              dpi: float | None = None, uri: str | None = None) -> Transcription:
    """Read ALTO (v1-v4, any namespace or none) into a ``Transcription`` in pixel coordinates.

    Coordinates are scaled to the image when ``image_width``/``image_height`` are given and the
    ``Page`` has ``WIDTH``/``HEIGHT`` (this also corrects pixel ALTO made on a master of another
    resolution). Without the image size, ``pixel`` files are read as they are and ``mm10`` /
    ``inch1200`` files need ``dpi``; otherwise a ``ValueError`` is raised.
    """
    root, ns = X.parse_xml(data)
    desc = X.child(root, "Description")
    unit = "pixel"
    file_name = None
    if desc is not None:
        mu = X.child(desc, "MeasurementUnit")
        if mu is not None and mu.text:
            unit = mu.text.strip()
        sii = X.child(desc, "sourceImageInformation")
        if sii is not None:
            fn = X.child(sii, "fileName")
            file_name = fn.text.strip() if fn is not None and fn.text else None
    layout = X.child(root, "Layout")
    page = X.child(layout, "Page") if layout is not None else None
    page_w = X.parse_num(page.get("WIDTH")) if page is not None else None
    page_h = X.parse_num(page.get("HEIGHT")) if page is not None else None
    sc = _scale_for(unit, page_w, page_h, image_width, image_height, dpi)

    tags: dict[str, etree._Element] = {}
    tags_el = X.child(root, "Tags")
    if tags_el is not None:
        for tg in tags_el:
            if isinstance(tg.tag, str) and tg.get("ID"):
                tags[tg.get("ID")] = tg
    ro_el = X.child(root, "ReadingOrder")
    ro_refs = _reading_order_refs(ro_el) if ro_el is not None else None

    t = Transcription()
    region_ro_ext: dict[str, Any] = {}
    real_ids_in_doc: list[str] = []
    line_no = 0
    gen = 0
    if page is not None:
        for el in page.iter("TextBlock", "Illustration"):
            label = raw = None
            ext: dict[str, Any] = {}
            for ref in (el.get("TAGREFS") or "").split():
                tg = tags.get(ref)
                if tg is None:
                    continue
                kind = tg.get("TYPE")
                if kind == X.EXT_KEY:
                    ext.update(X.ext_loads(tg.get("DESCRIPTION")))
                elif kind == "label":
                    label = tg.get("LABEL")
                elif kind == "raw_label":
                    raw = tg.get("LABEL")
                elif raw is None and tg.get("LABEL"):
                    raw = tg.get("LABEL")
            synthetic = bool(ext.get("synthetic"))
            bid = el.get("ID")
            if not bid:
                gen += 1
                bid = f"block_{gen}"
            bbox = sc.box(el)
            shape = el.find("Shape/Polygon")
            polygon = sc.points(X.parse_points(shape.get("POINTS"))) if shape is not None else None
            lines = [] if el.tag == "Illustration" else X.children(el, "TextLine")
            parsed = []
            for row, tl in enumerate(lines):
                parsed.append(_line(tl, row, line_no, None if synthetic else bid, sc, tags))
                line_no += 1
            if bbox is None:
                if polygon:
                    bbox = X.bounds(polygon)
                elif parsed:
                    bbox = X.unit_bbox(parsed)
                else:
                    bbox = [0.0, 0.0, 0.0, 0.0]
            t.lines.extend(parsed)
            if synthetic:
                continue
            if el.tag == "Illustration":
                raw = raw if raw is not None else (el.get("TYPE") or "")
                label = label or X.docling_from_raw(el.get("TYPE"), "picture")
            else:
                label = label or X.docling_from_raw(raw)
            t.regions.append(Region(
                id=bid, label=label, raw_label=raw or "", polygon=polygon or X.rect(bbox), bbox=bbox,
                score=ext.get("score"), heading_level=ext.get("heading_level"),
            ))
            real_ids_in_doc.append(bid)
            if "reading_order" in ext:
                region_ro_ext[bid] = ext["reading_order"]

    # region reading order: rank in ReadingOrder (blocks not in it: None); without ReadingOrder the
    # document order (ALTO's implicit order)
    real = set(real_ids_in_doc)
    if ro_refs is not None:
        seq = [r for r in dict.fromkeys(ro_refs) if r in real]
    else:
        seq = real_ids_in_doc
    rank = {rid: i for i, rid in enumerate(seq)}
    for r in t.regions:
        r.reading_order = region_ro_ext[r.id] if r.id in region_ro_ext else rank.get(r.id)

    t.source = Source(
        kind="converted", format="alto", uri=uri or file_name,
        image_width=image_width or (round(page_w * sc.sx) if page_w else None),
        image_height=image_height or (round(page_h * sc.sy) if page_h else None),
        extra={k: v for k, v in {"namespace": ns, "measurement_unit": unit if unit != "pixel" else None,
                                  "scale": None if sc.identity else [sc.sx, sc.sy]}.items() if v},
    )
    return t


def _line(tl, row: int, rank: int, region_id: str | None, sc: _Scale, tags) -> Line:
    ext: dict[str, Any] = {}
    for ref in (tl.get("TAGREFS") or "").split():
        tg = tags.get(ref)
        if tg is not None and tg.get("TYPE") == X.EXT_KEY:
            ext.update(X.ext_loads(tg.get("DESCRIPTION")))
    lid = tl.get("ID") or f"line_{rank}"
    bbox = sc.box(tl)
    shape = tl.find("Shape/Polygon")
    polygon = sc.points(X.parse_points(shape.get("POINTS"))) if shape is not None else None

    words: list[Word] = []
    strings = []
    hyp = None
    for c in tl:
        if c.tag == "String":
            strings.append(c)
        elif c.tag == "HYP":
            hyp = c.get("CONTENT") or ""
    for k, s in enumerate(strings):
        wb = sc.box(s)
        alts = [a.text or "" for a in X.children(s, "ALTERNATIVE")]
        words.append(Word(id=s.get("ID") or f"{lid}_w{k}", text=s.get("CONTENT") or "", bbox=wb,
                          confidence=X.parse_num(s.get("WC")), alternatives=alts))
    if hyp is not None and words:
        words[-1].text += hyp
        words[-1].hyphen = True
    for wid in ext.get("hyphen", []):
        for w in words:
            if w.id == wid:
                w.hyphen = True

    if bbox is None:
        boxes = [w.bbox for w in words if w.bbox]
        if polygon:
            bbox = X.bounds(polygon)
        elif boxes:
            x0 = min(b[0] for b in boxes)
            y0 = min(b[1] for b in boxes)
            x1 = max(b[0] + b[2] for b in boxes)
            y1 = max(b[1] + b[3] for b in boxes)
            bbox = [x0, y0, x1 - x0, y1 - y0]
        else:
            bbox = [0.0, 0.0, 0.0, 0.0]

    baseline = None
    bl = tl.get("BASELINE")
    if bl:
        pts = X.parse_points(bl)
        if pts is not None:
            baseline = sc.points(pts)
        else:
            y = X.parse_num(bl)
            if y is not None:      # ALTO < 4.2: one vertical position
                yy = sc.y(y)
                baseline = [[bbox[0], yy], [bbox[0] + bbox[2], yy]]

    if ext.get("wordless"):
        text = "".join(w.text for w in words)
        confidence = words[0].confidence if words else None
        words = []
    else:
        text = " ".join(w.text for w in words) if words else None
        confidence = X.mean_confidence((w.text, w.confidence) for w in words)
    if "text" in ext:
        text = ext["text"]
    if "confidence" in ext:
        confidence = ext["confidence"]
    return Line(
        id=lid, region_id=region_id, reading_order=ext.get("reading_order", rank), row=ext.get("row", row),
        bbox=bbox, polygon=polygon, baseline=baseline, score=ext.get("score"), text=text,
        confidence=confidence, alternatives=ext.get("alternatives", []), words=words,
    )
