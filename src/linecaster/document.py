"""Document assembly: a ``Transcription``'s regions, lines and tables -> its ``docling`` part (a
``DoclingDocument``), and the Markdown and text exports of it.

Ported from squiddleocr's ``document.py`` (``DocumentBuilder``, main ``7c8a052``). ``text="lines"``
(squiddleocr's ``--text lines``): one Docling item per region, in reading order (regions without an order last, in list order),
its text one visual row per line (the region's lines with the same ``Line.row`` joined with a space,
rows joined with ``\\n``), one provenance entry with the region's box:

- ``title`` -> title, ``section_header`` -> heading at ``Region.heading_level`` (retyper; 1 when unset),
  ``text``/``caption``/``footnote``/``list_item``/... -> text items with Docling's label;
- ``page_header``/``page_footer`` -> Docling's **furniture** content layer (always; the exports choose
  whether to include it: ``furniture=True`` gives what squiddleocr's ``--furniture`` gives);
- a region with ``extra["table"]`` (the tables step) -> a table item (cells with text, spans, header
  flag and box); with ``extra["formula"]`` (LaTeX from a formula step) -> a formula item;
- any other region (picture, chart, a table without a structure) -> a picture, with the text read
  inside it as a child text item.

Empty regions produce no item. ``build_docling`` makes the document of one page (page 1);
``DocumentBuilder`` makes one for all pages of an item, with paragraphs continued across page breaks,
optional sections and the region map for Markdown dividers (squiddleocr's ``--per-document``,
``--sections``, ``--dividers``). Exports (``export``): Markdown, text, HTML, DocLang and JSON, all
docling-core's own serialisers.

``text="reflow"`` is squiddleocr's default document mode (``linecaster.reflow``): the rows of a text
region joined into paragraphs, the typesetter's division marks removed (the page's own words as the
lexicon for the ambiguous case), one item per paragraph with a provenance entry per row, and a
paragraph that runs on continued into the next text region of the page.
"""
from __future__ import annotations

from typing import Any

from .geometry import BBox, bbox_of
from .transcription.model import Line, Region, Transcription

TEXT_LABELS = {
    "text": "text", "paragraph": "text", "title": "title", "section_header": "section_header",
    "caption": "caption", "footnote": "footnote", "page_header": "page_header", "page_footer": "page_footer",
    "list_item": "list_item", "formula": "formula", "code": "code", "reference": "reference",
    "document_index": "document_index",
}
FURNITURE = ("page_header", "page_footer")


def region_text(lines: list[Line]) -> str:
    """One visual row per line: the lines with the same ``row`` joined with a space, in row order."""
    return "\n".join(row.text for row in region_rows(lines))


def _box(b: BBox):
    from docling_core.types.doc import BoundingBox, CoordOrigin

    return BoundingBox(l=b.x0, t=b.y0, r=b.x1, b=b.y1, coord_origin=CoordOrigin.TOPLEFT)


def _prov(b: BBox, text: str = "", page_no: int = 1):
    from docling_core.types.doc import ProvenanceItem

    return ProvenanceItem(page_no=page_no, bbox=_box(b), charspan=(0, len(text)))


def _xywh_box(v) -> BBox | None:
    if not v:
        return None
    x, y, w, h = v
    return BBox(x, y, x + w, y + h)


def _table_data(table: dict):
    from docling_core.types.doc import TableCell, TableData

    cells = []
    for c in table.get("cells", []):
        b = _xywh_box(c.get("bbox"))
        rs, cs = c.get("row_span", 1), c.get("col_span", 1)
        cells.append(TableCell(text=c["text"], start_row_offset_idx=c["row"], end_row_offset_idx=c["row"] + rs,
                               start_col_offset_idx=c["col"], end_col_offset_idx=c["col"] + cs, row_span=rs,
                               col_span=cs, column_header=bool(c.get("header")), bbox=_box(b) if b else None))
    return TableData(table_cells=cells, num_rows=table.get("num_rows", 0), num_cols=table.get("num_cols", 0))


def region_rows(lines: list[Line]):
    """The region's visual rows (``reflow.Row``): text of the lines on each row joined with a space,
    the row's box the union of their boxes, in row order (squiddleocr's ``RegionContent.rows``)."""
    from .reflow import Row
    from .retyper import line_bbox

    grouped: dict[int, list[Line]] = {}
    for ln in lines:
        grouped.setdefault(ln.row, []).append(ln)
    out = []
    for i, k in enumerate(sorted(grouped)):
        boxes = [line_bbox(ln) for ln in grouped[k]]
        b = BBox(min(x.x0 for x in boxes), min(x.y0 for x in boxes), max(x.x1 for x in boxes), max(x.y1 for x in boxes))
        out.append(Row(" ".join(ln.text for ln in grouped[k] if ln.text), b, i))
    return out


TEXT_MODES = ("lines", "reflow")
#: ``Transcription.extra`` key of the Docling item -> ``"<page_no>:<region id>"`` map (``AssembleDocument``)
REGION_MAP_KEY = "docling_region_of"


class DocumentBuilder:
    """One ``DoclingDocument`` for one page or for all pages of an item, in order (squiddleocr's
    ``DocumentBuilder``; ``add_page`` once per page). Page ``n`` of the document is the ``n``-th page added
    (``page_no`` in every provenance entry).

    ``text``: ``lines`` or ``reflow`` (see the module docstring). In reflow mode the lexicon grows with
    every page added and a paragraph left open at the foot of a page continues on the next page (an
    item of digits only, a page number, between them does not close it).

    ``sections``: every heading (title or section header) opens a Docling ``section`` group, named after
    it, that holds it and everything after it up to the next heading, across pages; items before the
    first heading stay in the body. Markdown and text read the same; JSON gains the tree. (squiddleocr
    7c8a052 crashes on reflow + sections when a title appears; here a title opens its section the same
    way in both modes: the group first, the title inside.)

    ``region_of`` maps each item's ``self_ref`` to ``"<page_no>:<region id>"``, for the Markdown
    dividers (``to_markdown(..., region_of=...)``)."""

    def __init__(self, name: str = "document", text: str = "lines", sections: bool = False, rtl: bool = False,
                 stats=None):
        from docling_core.types.doc import DoclingDocument

        from .reflow import Lexicon, Stats

        if text not in TEXT_MODES:
            raise ValueError(f"unknown text mode {text!r}; choose {', '.join(TEXT_MODES)}")
        self.doc = DoclingDocument(name=name)
        self.text_mode, self.sections, self.rtl = text, sections, rtl
        self.lexicon, self.stats = Lexicon(), stats if stats is not None else Stats()
        self._section = None      # the open section GroupItem, or None for the body
        self._open = None         # (TextItem, Paragraph, Margins) of a paragraph that may continue
        self._level = 1
        self.pages = 0
        self.region_of: dict[str, str] = {}

    # ------------------------------------------------------------------ pages
    def add_page(self, t: Transcription, width: int | None = None, height: int | None = None,
                 page_no: int | None = None) -> int:
        from docling_core.types.doc import Size

        self.pages += 1
        page_no = page_no or self.pages
        w, h = width or t.source.image_width, height or t.source.image_height
        if w and h:
            self.doc.add_page(page_no=page_no, size=Size(width=w, height=h))
        by_region: dict[str, list[Line]] = {}
        for ln in t.lines:
            by_region.setdefault(ln.region_id, []).append(ln)
        regions = sorted(t.regions, key=lambda r: r.reading_order if r.reading_order is not None else 1 << 30)
        if self.text_mode == "reflow":
            for r in regions:
                self.lexicon.add(region_text(by_region.get(r.id, [])))
        for r in regions:
            before = (len(self.doc.texts), len(self.doc.pictures), len(self.doc.tables))
            self._add_region(page_no, r, by_region.get(r.id, []))
            key = f"{page_no}:{r.id}"
            for items, n in zip((self.doc.texts, self.doc.pictures, self.doc.tables), before):
                for it in items[n:]:
                    self.region_of[it.self_ref] = key
        return page_no

    def build(self):
        """The document, validated by docling-core (``validate_document``: a consistent tree, and every
        provenance box clamped to its page, as docling-core does whenever it validates a document, e.g. on
        loading; its out-of-bounds warnings are silenced, layout boxes often reach a few pixels past the edge)."""
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*outside page bounds.*", category=UserWarning)
            self.doc.validate_document()
        return self.doc

    # ---------------------------------------------------------------- regions
    def _add_region(self, page_no: int, r: Region, lines: list[Line]) -> None:
        from docling_core.types.doc import DocItemLabel

        b = bbox_of(r.polygon)
        self._level = r.heading_level or 1
        formula, table = r.extra.get("formula"), r.extra.get("table")
        if self.text_mode == "reflow" and formula is None and table is None and r.label in TEXT_LABELS:
            self._add_reflowed(page_no, r, region_rows(lines))
            return
        self._open = None
        content = region_text(lines)
        if formula is not None:
            if formula.strip():
                self.doc.add_text(label=DocItemLabel.FORMULA, text=formula, prov=_prov(b, formula, page_no),
                                  parent=self._section)
        elif table is not None:
            self.doc.add_table(data=_table_data(table), prov=_prov(b, "", page_no), parent=self._section)
        elif r.label in TEXT_LABELS:
            if content.strip():
                self._add_text(DocItemLabel(TEXT_LABELS[r.label]), content, _prov(b, content, page_no))
        else:
            pic = self.doc.add_picture(prov=_prov(b, "", page_no), parent=self._section)
            if content.strip():
                self.doc.add_text(label=DocItemLabel.TEXT, text=content, prov=_prov(b, content, page_no), parent=pic)

    def _open_section(self, text: str) -> None:
        from docling_core.types.doc import GroupLabel

        if self.sections:
            self._section = self.doc.add_group(label=GroupLabel.SECTION, name=" ".join(text.split())[:80])

    def _add_text(self, label, text: str, prov):
        from docling_core.types.doc import DocItemLabel

        if label in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER):
            self._open_section(text)
        if label == DocItemLabel.TITLE:
            return self.doc.add_title(text=text, prov=prov, parent=self._section)
        if label == DocItemLabel.SECTION_HEADER:
            return self.doc.add_heading(text=text, prov=prov, parent=self._section, level=self._level)
        return self.doc.add_text(label=label, text=text, prov=prov, parent=self._section, content_layer=_layer(label))

    def _add_reflowed(self, page_no: int, r: Region, rows) -> None:
        from docling_core.types.doc import DocItemLabel

        from .reflow import Margins, continues, join_paragraphs, reflow_rows

        label = DocItemLabel(TEXT_LABELS[r.label])
        single = label in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER)
        paragraphs = reflow_rows(rows, self.rtl, self.lexicon, single, self.stats)
        if not paragraphs:
            return
        m = Margins.of([row for row in rows if row.text.strip()], self.rtl)
        if len(paragraphs) == 1 and not any(ch.isalpha() for ch in paragraphs[0].text):
            # furniture (a page number, whatever the layout called it): added; an open paragraph stays open,
            # so a sentence continues over the page break
            provs = _row_provs(rows, paragraphs[0], page_no=page_no)
            item = self.doc.add_text(label=label, text=paragraphs[0].text, prov=provs[0], parent=self._section,
                                     content_layer=_layer(label))
            item.prov.extend(provs[1:])
            return
        if self._open is not None and label == DocItemLabel.TEXT and continues(self._open[1], rows[paragraphs[0].spans[0].row], m, self.rtl):
            item, prev = self._open[0], self._open[1]
            first = paragraphs.pop(0)
            joined = join_paragraphs(prev, first, self.lexicon, self.stats)
            offset = len(joined) - len(first.text)
            item.text = item.orig = joined
            item.prov.extend(_row_provs(rows, first, offset, page_no))
            prev.text, prev.open_end = joined, first.open_end
            self.stats.continuations += 1
            self.stats.paragraphs -= 1
            if not paragraphs and first.open_end:
                self._open = (item, prev, m)
                return
        self._open = None
        for para in paragraphs:
            provs = _row_provs(rows, para, page_no=page_no)
            if single:
                item = self._add_text(label, para.text, provs[0])
            else:
                item = self.doc.add_text(label=label, text=para.text, prov=provs[0], parent=self._section,
                                         content_layer=_layer(label))
            item.prov.extend(provs[1:])
            if para.open_end and label == DocItemLabel.TEXT:
                self._open = (item, para, m)


def build_docling(t: Transcription, name: str = "page", width: int | None = None, height: int | None = None,
                  text: str = "lines", rtl: bool = False, stats=None, sections: bool = False):
    """The ``DoclingDocument`` of one page (``DocumentBuilder`` with one page)."""
    b = DocumentBuilder(name, text=text, sections=sections, rtl=rtl, stats=stats)
    b.add_page(t, width, height)
    return b.build()


def _layer(label):
    from docling_core.types.doc import ContentLayer, DocItemLabel

    return ContentLayer.FURNITURE if label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER) else None


def _row_provs(rows, para, offset: int = 0, page_no: int = 1):
    from docling_core.types.doc import ProvenanceItem

    by_index = {row.index: row for row in rows}
    return [ProvenanceItem(page_no=page_no, bbox=_box(by_index[s.row].bbox), charspan=(s.start + offset, s.end + offset))
            for s in para.spans if s.row in by_index]


def docling_dict(doc) -> dict[str, Any]:
    return doc.export_to_dict()


def load_docling(t: Transcription):
    from docling_core.types.doc import DoclingDocument

    if t.docling is None:
        raise ValueError("the transcription has no docling part (run the document assembly first)")
    return DoclingDocument.model_validate(t.docling)


def _layers(furniture: bool):
    from docling_core.types.doc import ContentLayer

    return {ContentLayer.BODY, ContentLayer.FURNITURE} if furniture else {ContentLayer.BODY}


def _span_aware_table_serializer():
    """Docling's pipe table for a plain grid, its HTML table when a cell spans (squiddleocr's rule:
    the pipe table repeats a spanning cell's text in every cell it covers)."""
    from docling_core.transforms.serializer.html import HTMLTableSerializer
    from docling_core.transforms.serializer.markdown import MarkdownTableSerializer

    class SpanAwareTableSerializer(MarkdownTableSerializer):
        def serialize(self, *, item, doc_serializer, doc, **kwargs):
            if any(c.row_span > 1 or c.col_span > 1 for c in item.data.table_cells):
                return HTMLTableSerializer().serialize(item=item, doc_serializer=doc_serializer, doc=doc, **kwargs)
            return super().serialize(item=item, doc_serializer=doc_serializer, doc=doc, **kwargs)

        def get_header_and_body_lines(self, *, table_text, **kwargs):
            if table_text.lstrip().startswith("<table"):
                return HTMLTableSerializer().get_header_and_body_lines(table_text=table_text, **kwargs)
            return super().get_header_and_body_lines(table_text=table_text, **kwargs)

    return SpanAwareTableSerializer()


def to_markdown(doc_or_t, furniture: bool = False, region_of: dict[str, str] | None = None) -> str:
    """Markdown with Docling's defaults, tables with spanning cells as HTML; page headers and footers
    only with ``furniture``. With ``region_of`` (``DocumentBuilder.region_of``) a ``---`` rule separates
    the items of one layout region from the next (squiddleocr's ``--dividers``)."""
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer, MarkdownParams
    from docling_core.types.doc import GroupItem

    doc = load_docling(doc_or_t) if isinstance(doc_or_t, Transcription) else doc_or_t
    layers = _layers(furniture)
    ser = MarkdownDocSerializer(doc=doc, table_serializer=_span_aware_table_serializer(),
                                params=MarkdownParams(layers=layers))
    if not region_of:
        return ser.serialize().text
    blocks: list[str] = []
    last = None
    for item, _level in doc.iterate_items(included_content_layers=layers):
        if isinstance(item, GroupItem):
            continue
        text = ser.serialize(item=item).text
        if not text.strip():
            continue
        key = region_of.get(item.self_ref)
        if blocks and key != last:
            blocks.append("---")
        blocks.append(text)
        last = key
    return "\n\n".join(blocks)


def to_text(doc_or_t, furniture: bool = False) -> str:
    """Docling's plain-text export; page headers and footers only with ``furniture``."""
    doc = load_docling(doc_or_t) if isinstance(doc_or_t, Transcription) else doc_or_t
    return doc.export_to_text(included_content_layers=_layers(furniture))


def to_html(doc_or_t, furniture: bool = False) -> str:
    """Docling's HTML export (its own defaults); page headers and footers only with ``furniture``."""
    doc = load_docling(doc_or_t) if isinstance(doc_or_t, Transcription) else doc_or_t
    return doc.export_to_html(included_content_layers=_layers(furniture))


def to_doclang(doc_or_t) -> str:
    """Docling's DocLang XML, with named groups (sections survive as ``<group>``). DocLang keeps every
    content layer and marks the furniture items (``<layer value="furniture"/>``), so it has no
    ``furniture`` switch."""
    doc = load_docling(doc_or_t) if isinstance(doc_or_t, Transcription) else doc_or_t
    return doc.export_to_doclang(add_named_groups=True)


def to_json(doc_or_dict) -> str:
    """The DoclingDocument as JSON, formatted as docling-core's ``save_as_json`` writes it (indent 2,
    ASCII-escaped)."""
    import json

    if isinstance(doc_or_dict, Transcription):
        doc_or_dict = doc_or_dict.docling
    data = doc_or_dict if isinstance(doc_or_dict, dict) else docling_dict(doc_or_dict)
    return json.dumps(data, indent=2)


#: document export formats (``export``) -> file extension
EXPORT_FORMATS = {"md": "md", "txt": "txt", "html": "html", "doclang": "doclang.xml", "json": "json"}


def export(doc, fmt: str, furniture: bool = False, region_of: dict[str, str] | None = None) -> str:
    """One export of a ``DoclingDocument`` (or of a transcription's ``docling`` part): ``md``
    (``region_of`` puts ``---`` dividers between layout regions), ``txt``, ``html``, ``doclang`` or
    ``json``. ``furniture`` keeps page headers and footers in md, txt and html (json and doclang
    always hold them, in Docling's furniture layer)."""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"unknown export format {fmt!r}; choose from {', '.join(EXPORT_FORMATS)}")
    if fmt == "json":
        return to_json(doc)
    if isinstance(doc, (Transcription, dict)):
        doc = load_docling(doc) if isinstance(doc, Transcription) else _validate(doc)
    if fmt == "md":
        return to_markdown(doc, furniture, region_of)
    if fmt == "txt":
        return to_text(doc, furniture)
    if fmt == "html":
        return to_html(doc, furniture)
    return to_doclang(doc)


def _validate(data: dict):
    from docling_core.types.doc import DoclingDocument

    return DoclingDocument.model_validate(data)
