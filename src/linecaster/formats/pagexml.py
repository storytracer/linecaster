"""PAGE-XML (writes the 2019-07-15 schema; reads 2009 to 2019 namespaces) on lxml.

Mapping (see ``docs/reference/serialization.md``):

* region -> ``TextRegion`` with ``@type`` from its Docling label (``ImageRegion``, ``ChartRegion``,
  ``TableRegion``, ``MathsRegion`` for picture, chart, table and formula regions without lines);
  the producer's label in ``@custom`` as ``structure {type:<raw_label>;}`` (the Transkribus
  convention); the detection score as ``Coords/@conf``; reading order as
  ``ReadingOrder/OrderedGroup/RegionRefIndexed``;
* line -> ``TextLine`` (``Coords`` = polygon, or the box when there is none; ``Baseline``;
  ``TextEquiv`` with ``@conf``; alternatives as further ``TextEquiv`` with ``@index``);
* word -> ``Word`` (``Coords`` = box, ``TextEquiv``);
* lines without a region go into a synthetic ``TextRegion`` the reader drops again;
* each step of ``model`` -> ``Metadata/MetadataItem[@type="processingStep"]`` (``name`` the step, ``value``
  the preset edition or model, ``Labels`` of the ``linecaster`` model for the rest), read back into
  ``model`` (foreign files: OCR-D's processing steps with their parameters).

PAGE coordinates are non-negative integers: geometry is rounded half up (boxes by their corners)
and clamped at 0. What PAGE has no place for goes into ``UserDefined/UserAttribute[@name=
"linecaster"]``, only when a reader would infer something else.
"""
from __future__ import annotations

import re
from typing import Any

from lxml import etree

from ..data.transcription import Line, ModelInfo, Region, Source, Transcription, Word
from . import _provenance as P, _xml as X

NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = f"{NS} {NS}/pagecontent.xsd"
DEFAULT_CREATED = "1970-01-01T00:00:00"
_STRUCTURE = re.compile(r"structure\s*\{([^}]*)\}")


def _e(parent, tag: str, **attrs) -> etree._Element:
    el = etree.SubElement(parent, f"{{{NS}}}{tag}")
    for k, v in attrs.items():
        if v is not None:
            el.set(k, str(v))
    return el


def _escape_custom(v: str) -> str:
    # the custom attribute's syntax reserves ; { } and \ ; escape them as \uXXXX (Transkribus style)
    return "".join(f"\\u{ord(c):04x}" if c in ";{}\\" else c for c in v)


def _unescape_custom(v: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), v)


def structure_type(custom: str | None) -> str | None:
    if not custom:
        return None
    m = _STRUCTURE.search(custom)
    if not m:
        return None
    for part in m.group(1).split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            if k.strip() == "type":
                return _unescape_custom(v.strip())
    return None


def page_label(element: str, type_attr: str | None, structure: str | None) -> str:
    """The Docling label a reader gives a PAGE region."""
    if element != "TextRegion":
        return X.PAGE_ELEMENT_TO_DOCLING.get(element, "text")
    if structure and structure.strip().lower() in X.RAW_TO_DOCLING:
        return X.RAW_TO_DOCLING[structure.strip().lower()]
    return X.docling_from_raw(type_attr)


def page_raw_label(element: str, type_attr: str | None, structure: str | None) -> str:
    if structure:
        return structure
    if element == "TextRegion":
        return type_attr or ""
    return element


def _conf(v: float | None) -> str | None:
    return None if v is None else repr(float(v))


class _Writer:
    def __init__(self, t: Transcription, extensions: bool):
        self.t = t
        self.qz = X.Quantizer(0, clamp=True)
        self.extensions = extensions

    def ext(self, el, data: dict[str, Any]) -> None:
        if data and self.extensions:
            ud = _e(el, "UserDefined")
            _e(ud, "UserAttribute", name=X.EXT_KEY, type="xsd:string", value=X.ext_dumps(data))

    def coords(self, parent, points, conf=None):
        pts = self.qz.points(points)
        if len(pts) == 1:
            pts = pts * 2
        return _e(parent, "Coords", points=X.fmt_points(pts, 0), conf=_conf(conf)), pts

    def text_equivs(self, parent, text: str | None, conf: float | None, alternatives: list[str]):
        if text is None:
            return
        te = _e(parent, "TextEquiv", index="1" if alternatives else None, conf=_conf(conf))
        _e(te, "Unicode").text = text
        for i, alt in enumerate(alternatives, start=2):
            te = _e(parent, "TextEquiv", index=str(i))
            _e(te, "Unicode").text = alt

    def region(self, page, r: Region, lines: list[Line], predicted_ro, pos) -> None:
        element = "TextRegion"
        if not lines and r.label in X.DOCLING_TO_PAGE_ELEMENT:
            element = X.DOCLING_TO_PAGE_ELEMENT[r.label]
        type_attr = X.DOCLING_TO_PAGE_TEXT.get(r.label, "paragraph") if element == "TextRegion" else None
        el = _e(page, element, id=r.id)
        if r.raw_label:
            el.set("custom", f"structure {{type:{_escape_custom(r.raw_label)};}}")
        if type_attr:
            el.set("type", type_attr)
        _, pts = self.coords(el, r.polygon, r.score)
        ext: dict[str, Any] = {}
        structure = r.raw_label or None
        if page_label(element, type_attr, structure) != r.label:
            ext["label"] = r.label
        if page_raw_label(element, type_attr, structure) != r.raw_label:
            ext["raw_label"] = r.raw_label
        want = self.qz.box(r.bbox)
        if not X.same_box(X.bounds(pts), want):
            ext["bbox"] = want
        if r.heading_level is not None:
            ext["heading_level"] = r.heading_level
        if r.reading_order != predicted_ro:
            ext["reading_order"] = r.reading_order
        self.ext(el, ext)
        for ln in lines:
            self.line(el, ln, pos)

    def synthetic(self, page, block_id: str, lines: list[Line], pos) -> None:
        el = _e(page, "TextRegion", id=block_id)
        self.coords(el, X.rect(X.unit_bbox(lines)))
        self.ext(el, {"synthetic": True})
        for ln in lines:
            self.line(el, ln, pos)

    def line(self, region_el, ln: Line, pos) -> None:
        el = _e(region_el, "TextLine", id=ln.id)
        ext = X.line_order_ext(ln, pos)
        want = self.qz.box(ln.bbox)
        if ln.polygon:
            _, pts = self.coords(el, ln.polygon, ln.score)
            if not X.same_box(X.bounds(pts), want):
                ext["bbox"] = want
        else:
            self.coords(el, X.rect(want), ln.score)
            ext["polygon"] = None
        if ln.baseline:
            bl = self.qz.points(ln.baseline)
            if len(bl) >= 2:
                _e(el, "Baseline", points=X.fmt_points(bl, 0))
            else:
                ext["baseline"] = bl
        hyphen = []
        for w in ln.words:
            self.word(el, w, ln)
            if w.hyphen:
                hyphen.append(w.id)
        if hyphen:
            ext["hyphen"] = hyphen
        self.text_equivs(el, ln.text, ln.confidence, ln.alternatives)
        if ln.text is None and ln.confidence is not None:
            ext["confidence"] = ln.confidence
        if ln.text is None and ln.words:
            ext["text"] = None
        if ln.text is None and ln.alternatives:
            ext["alternatives"] = ln.alternatives
        self.ext(el, ext)

    def word(self, line_el, w: Word, ln: Line) -> None:
        el = _e(line_el, "Word", id=w.id)
        ext: dict[str, Any] = {}
        if w.bbox is not None:
            self.coords(el, X.rect(self.qz.box(w.bbox)))
        else:
            self.coords(el, X.rect(self.qz.box(ln.bbox)))
            ext["bbox"] = None
        self.text_equivs(el, w.text, w.confidence, w.alternatives)
        self.ext(el, ext)

    def processing_step(self, md, m: ModelInfo) -> None:
        """``MetadataItem type="processingStep"`` (as OCR-D records its processors): ``name`` = the step,
        ``value`` = the preset edition or the model; ``Labels`` of the ``linecaster`` model with the model
        (``externalId="model"``: name, revision, preset, preset hash, backend, software) and the settings
        (``externalId="settings"``: one label per setting, values as ``encode_value`` writes them)."""
        when = P.processed_at(m)
        item = _e(md, "MetadataItem", type="processingStep", name=m.step, value=P.label(m),
                  date=when if when and P.is_datetime(when) else None)
        labels = _e(item, "Labels", externalModel=P.SOFTWARE, externalId="model")
        rec = P.record(m)
        for k in P.RECORD_KEYS:
            if k not in ("step", "settings") and k in rec:
                _e(labels, "Label", type=k, value=rec[k])
        _e(labels, "Label", type="software", value=P.software())
        if m.settings:
            labels = _e(item, "Labels", externalModel=P.SOFTWARE, externalId="settings")
            for k, v in m.settings.items():
                _e(labels, "Label", type=str(k), value=P.encode_value(v))

    def write(self, width: int, height: int, uri: str | None, created: str) -> bytes:
        t = self.t
        units = X.units_in_order(t)
        in_group = [u for u in units if u.synthetic or u.region.reading_order is not None]
        ranks = X.region_ranks(units) if in_group else {u.region.id: i for i, u in enumerate(units)}
        pos = X.line_positions(units)

        root = etree.Element(f"{{{NS}}}PcGts", nsmap={None: NS, "xsi": XSI})
        root.set(f"{{{XSI}}}schemaLocation", SCHEMA_LOCATION)
        md = _e(root, "Metadata")
        _e(md, "Creator").text = P.software()
        _e(md, "Created").text = created
        _e(md, "LastChange").text = created
        if t.model:
            _e(md, "Comments").text = "; ".join(P.summary(m) for m in t.model)
        for m in t.model:
            self.processing_step(md, m)
        page = _e(root, "Page", imageFilename=uri or "", imageWidth=str(width), imageHeight=str(height))
        if in_group:
            ro = _e(page, "ReadingOrder")
            used = {r.id for r in t.regions} | {u.block_id for u in units}
            gid, k = "lc_reading_order", 0
            while gid in used:
                k += 1
                gid = f"lc_reading_order_{k}"
            grp = _e(ro, "OrderedGroup", id=gid)
            for i, u in enumerate(in_group):
                _e(grp, "RegionRefIndexed", index=str(i), regionRef=u.block_id)
        for u in units:
            if u.synthetic:
                self.synthetic(page, u.block_id, u.lines, pos)
            else:
                self.region(page, u.region, u.lines, ranks.get(u.region.id), pos)
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def to_page(t: Transcription, *, image_width: int | None = None, image_height: int | None = None,
            image_uri: str | None = None, created: str = DEFAULT_CREATED, extensions: bool = True) -> bytes:
    """Serialize ``t`` as PAGE-XML 2019-07-15.

    ``created`` fills ``Metadata/Created`` and ``LastChange``; it defaults to a fixed timestamp so
    the output is byte-reproducible (pass the run's UTC time if wanted). ``extensions=False`` leaves
    out the ``UserDefined`` extension (the file then only round-trips what PAGE itself holds).
    """
    width = image_width if image_width is not None else t.source.image_width
    height = image_height if image_height is not None else t.source.image_height
    if width is None or height is None:
        raise ValueError("to_page needs the image size (image_width/image_height or t.source)")
    uri = image_uri if image_uri is not None else t.source.uri
    return _Writer(t, extensions).write(int(width), int(height), uri, created)


# ================================================================ reading


def _ext(el) -> dict[str, Any]:
    ud = X.child(el, "UserDefined")
    if ud is None:
        return {}
    out: dict[str, Any] = {}
    for ua in X.children(ud, "UserAttribute"):
        if ua.get("name") == X.EXT_KEY:
            out.update(X.ext_loads(ua.get("value")))
    return out


def _points(el) -> list[list[float]] | None:
    c = X.child(el, "Coords")
    if c is None:
        return None
    if c.get("points") is not None:
        return X.parse_points(c.get("points"))
    pts = [[X.parse_num(p.get("x")) or 0.0, X.parse_num(p.get("y")) or 0.0] for p in X.children(c, "Point")]
    return pts or None


def _baseline(el) -> list[list[float]] | None:
    b = X.child(el, "Baseline")
    if b is None:
        return None
    if b.get("points") is not None:
        return X.parse_points(b.get("points"))
    pts = [[X.parse_num(p.get("x")) or 0.0, X.parse_num(p.get("y")) or 0.0] for p in X.children(b, "Point")]
    return pts or None


def _text_equivs(el) -> tuple[str | None, float | None, list[str]]:
    tes = X.children(el, "TextEquiv")
    if not tes:
        return None, None, []

    def key(te):
        v = X.parse_num(te.get("index"))
        return v if v is not None else 0.0

    tes = sorted(tes, key=key)

    def text(te):
        u = X.child(te, "Unicode")
        if u is not None:
            return u.text or ""
        p = X.child(te, "PlainText")
        return (p.text or "") if p is not None else ""

    return text(tes[0]), X.parse_num(tes[0].get("conf")), [text(te) for te in tes[1:]]


def _coords_conf(el) -> float | None:
    c = X.child(el, "Coords")
    return X.parse_num(c.get("conf")) if c is not None else None


def _ro_refs(ro) -> list[str]:
    refs: list[str] = []

    def walk(group):
        kids = [c for c in group if isinstance(c.tag, str)]
        if group.tag.startswith("OrderedGroup"):
            kids.sort(key=lambda c: X.parse_num(c.get("index")) or 0.0)
        for c in kids:
            if c.tag in ("RegionRefIndexed", "RegionRef"):
                refs.append(c.get("regionRef"))
            elif "Group" in c.tag:
                if c.get("regionRef"):
                    refs.append(c.get("regionRef"))
                walk(c)

    for g in ro:
        if isinstance(g.tag, str) and "Group" in g.tag:
            if g.get("regionRef"):
                refs.append(g.get("regionRef"))
            walk(g)
    return refs


def _metadata_steps(md) -> list[ModelInfo]:
    """``MetadataItem type="processingStep"`` -> ``ModelInfo``: linecaster's from their ``Labels``; foreign
    ones (OCR-D) with ``name`` as the step, ``value`` as the model, ``Label``s of other ``Labels`` (OCR-D's
    ``parameters``) as settings."""
    steps = []
    for item in X.children(md, "MetadataItem"):
        if item.get("type") != "processingStep":
            continue
        rec: dict[str, Any] = {"step": item.get("name"), "name": item.get("value")}
        settings: dict[str, Any] = {}
        for labels in X.children(item, "Labels"):
            ours = labels.get("externalModel") == P.SOFTWARE
            for lb in X.children(labels, "Label"):
                k, v = lb.get("type"), lb.get("value")
                if k is None or v is None:
                    continue
                if ours and labels.get("externalId") == "model":
                    if k in P.RECORD_KEYS:
                        rec[k] = v
                elif ours and labels.get("externalId") == "settings":
                    settings[k] = P.decode_value(v)
                else:
                    settings[k] = v
        if settings:
            rec["settings"] = settings
        m = P.from_record(rec)
        if item.get("date"):
            m.measurements["datetime"] = item.get("date")
        steps.append(m)
    return steps


def from_page(data: bytes | str, *, uri: str | None = None) -> Transcription:
    """Read PAGE-XML (2009-2019 namespaces, ``points`` attributes or ``Point`` children)."""
    root, ns = X.parse_xml(data)
    page = X.child(root, "Page")
    md = X.child(root, "Metadata")
    t = Transcription(model=_metadata_steps(md) if md is not None else [])
    if page is None:
        t.source = Source(kind="converted", format="page", uri=uri, extra={"namespace": ns} if ns else {})
        return t
    ro_el = X.child(page, "ReadingOrder")
    ro_refs = _ro_refs(ro_el) if ro_el is not None else None

    real_ids: list[str] = []
    region_ro_ext: dict[str, Any] = {}
    line_no = 0
    gen = 0
    for el in page.iter():
        if not isinstance(el.tag, str) or not el.tag.endswith("Region"):
            continue
        ext = _ext(el)
        rid = el.get("id")
        if not rid:
            gen += 1
            rid = f"region_{gen}"
        synthetic = bool(ext.get("synthetic"))
        polygon = _points(el)
        lines = X.children(el, "TextLine") if el.tag == "TextRegion" else []
        parsed = []
        for row, tl in enumerate(lines):
            parsed.append(_line(tl, row, line_no, None if synthetic else rid))
            line_no += 1
        t.lines.extend(parsed)
        if not polygon:     # a region without Coords: the box around its lines
            polygon = X.rect(X.unit_bbox(parsed) if parsed else [0.0, 0.0, 0.0, 0.0])
        if synthetic:
            continue
        type_attr = el.get("type")
        structure = structure_type(el.get("custom"))
        t.regions.append(Region(
            id=rid,
            label=ext.get("label", page_label(el.tag, type_attr, structure)),
            raw_label=ext.get("raw_label", page_raw_label(el.tag, type_attr, structure)),
            polygon=polygon, bbox=ext.get("bbox", X.bounds(polygon)), score=_coords_conf(el),
            heading_level=ext.get("heading_level"),
        ))
        real_ids.append(rid)
        if "reading_order" in ext:
            region_ro_ext[rid] = ext["reading_order"]

    real = set(real_ids)
    seq = [r for r in dict.fromkeys(ro_refs) if r in real] if ro_refs is not None else real_ids
    rank = {rid: i for i, rid in enumerate(seq)}
    for r in t.regions:
        r.reading_order = region_ro_ext[r.id] if r.id in region_ro_ext else rank.get(r.id)

    w = X.parse_num(page.get("imageWidth"))
    h = X.parse_num(page.get("imageHeight"))
    t.source = Source(kind="converted", format="page", uri=uri or page.get("imageFilename") or None,
                      image_width=int(w) if w else None, image_height=int(h) if h else None,
                      extra={"namespace": ns} if ns else {})
    return t


def _line(tl, row: int, rank: int, region_id: str | None) -> Line:
    ext = _ext(tl)
    lid = tl.get("id") or f"line_{rank}"
    polygon = _points(tl)
    words = []
    for k, we in enumerate(X.children(tl, "Word")):
        wext = _ext(we)
        wpts = _points(we)
        text, conf, alts = _text_equivs(we)
        if text is None:     # PAGE allows text on glyphs only
            text = "".join((_text_equivs(g)[0] or "") for g in X.children(we, "Glyph"))
        words.append(Word(id=we.get("id") or f"{lid}_w{k}", text=text,
                          bbox=wext["bbox"] if "bbox" in wext else (X.bounds(wpts) if wpts else None),
                          confidence=conf, alternatives=alts))
    for wid in ext.get("hyphen", []):
        for w in words:
            if w.id == wid:
                w.hyphen = True
    text, conf, alts = _text_equivs(tl)
    if "text" in ext:
        text = ext["text"]
    elif text is None and words:
        text = " ".join(w.text for w in words)
    if "bbox" in ext:
        bbox = ext["bbox"]
    elif polygon:
        bbox = X.bounds(polygon)
    else:
        bbox = [0.0, 0.0, 0.0, 0.0]
    return Line(
        id=lid, region_id=region_id, reading_order=ext.get("reading_order", rank), row=ext.get("row", row),
        bbox=bbox, polygon=ext["polygon"] if "polygon" in ext else polygon,
        baseline=ext["baseline"] if "baseline" in ext else _baseline(tl),
        score=_coords_conf(tl), text=text, confidence=ext.get("confidence", conf),
        alternatives=ext.get("alternatives", alts),
        words=words,
    )
