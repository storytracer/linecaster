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

Empty regions produce no item. Pages are numbered 1 (one document per page; a book-level document,
with paragraphs continued across pages, is a later block).

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


def build_docling(t: Transcription, name: str = "page", width: int | None = None, height: int | None = None,
                  text: str = "lines", rtl: bool = False, stats=None):
    """The ``DoclingDocument`` of one page (see the module docstring). ``width``/``height``: the page
    image's size (default: ``t.source.image_width``/``image_height``). ``text="reflow"``: rows joined
    into paragraphs (``linecaster.reflow``), one item per paragraph with a provenance entry per row, a
    paragraph continued into the next text region where it runs on; ``stats`` (``reflow.Stats``) sums
    the decisions."""
    from docling_core.types.doc import DocItemLabel, DoclingDocument, Size

    if text not in TEXT_MODES:
        raise ValueError(f"unknown text mode {text!r}; choose {', '.join(TEXT_MODES)}")
    doc = DoclingDocument(name=name)
    w, h = width or t.source.image_width, height or t.source.image_height
    if w and h:
        doc.add_page(page_no=1, size=Size(width=w, height=h))
    by_region: dict[str, list[Line]] = {}
    for ln in t.lines:
        by_region.setdefault(ln.region_id, []).append(ln)
    regions: list[Region] = sorted(t.regions, key=lambda r: r.reading_order if r.reading_order is not None else 1 << 30)
    flow = _Reflow(doc, rtl, stats) if text == "reflow" else None
    if flow is not None:
        for r in regions:
            flow.lexicon.add(region_text(by_region.get(r.id, [])))
    for r in regions:
        b = bbox_of(r.polygon)
        lines = by_region.get(r.id, [])
        formula, table = r.extra.get("formula"), r.extra.get("table")
        if flow is not None and formula is None and table is None and r.label in TEXT_LABELS:
            flow.add(r, region_rows(lines))
            continue
        if flow is not None:
            flow.open = None
        content = region_text(lines)
        if formula is not None:
            if formula.strip():
                doc.add_text(label=DocItemLabel.FORMULA, text=formula, prov=_prov(b, formula))
        elif table is not None:
            doc.add_table(data=_table_data(table), prov=_prov(b))
        elif r.label in TEXT_LABELS:
            if not content.strip():
                continue
            _add_text(doc, r, DocItemLabel(TEXT_LABELS[r.label]), content, _prov(b, content))
        else:
            pic = doc.add_picture(prov=_prov(b))
            if content.strip():
                doc.add_text(label=DocItemLabel.TEXT, text=content, prov=_prov(b, content), parent=pic)
    return doc


def _layer(label):
    from docling_core.types.doc import ContentLayer, DocItemLabel

    return ContentLayer.FURNITURE if label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER) else None


def _add_text(doc, r: Region, label, text: str, prov):
    from docling_core.types.doc import DocItemLabel

    if label == DocItemLabel.TITLE:
        return doc.add_title(text=text, prov=prov)
    if label == DocItemLabel.SECTION_HEADER:
        return doc.add_heading(text=text, prov=prov, level=r.heading_level or 1)
    return doc.add_text(label=label, text=text, prov=prov, content_layer=_layer(label))


def _row_provs(rows, para, offset: int = 0):
    from docling_core.types.doc import ProvenanceItem

    by_index = {row.index: row for row in rows}
    return [ProvenanceItem(page_no=1, bbox=_box(by_index[s.row].bbox), charspan=(s.start + offset, s.end + offset))
            for s in para.spans if s.row in by_index]


class _Reflow:
    """squiddleocr's ``DocumentBuilder._add_reflowed`` (without sections), for one page."""

    def __init__(self, doc, rtl: bool, stats):
        from .reflow import Lexicon, Stats

        self.doc, self.rtl = doc, rtl
        self.lexicon, self.stats = Lexicon(), stats if stats is not None else Stats()
        self.open = None       # (TextItem, Paragraph, Margins) of a paragraph that may continue

    def add(self, r: Region, rows) -> None:
        from docling_core.types.doc import DocItemLabel

        from .reflow import Margins, continues, join_paragraphs, reflow_rows

        label = DocItemLabel(TEXT_LABELS[r.label])
        single = label in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER)
        paragraphs = reflow_rows(rows, self.rtl, self.lexicon, single, self.stats)
        if not paragraphs:
            return
        m = Margins.of([row for row in rows if row.text.strip()], self.rtl)
        if len(paragraphs) == 1 and not any(ch.isalpha() for ch in paragraphs[0].text):
            # furniture (a page number, whatever the layout called it): added; an open paragraph stays open
            provs = _row_provs(rows, paragraphs[0])
            item = self.doc.add_text(label=label, text=paragraphs[0].text, prov=provs[0], content_layer=_layer(label))
            item.prov.extend(provs[1:])
            return
        if self.open is not None and label == DocItemLabel.TEXT and continues(self.open[1], rows[paragraphs[0].spans[0].row], m, self.rtl):
            item, prev = self.open[0], self.open[1]
            first = paragraphs.pop(0)
            joined = join_paragraphs(prev, first, self.lexicon, self.stats)
            offset = len(joined) - len(first.text)
            item.text = item.orig = joined
            item.prov.extend(_row_provs(rows, first, offset))
            prev.text, prev.open_end = joined, first.open_end
            self.stats.continuations += 1
            self.stats.paragraphs -= 1
            if not paragraphs and first.open_end:
                self.open = (item, prev, m)
                return
        self.open = None
        for para in paragraphs:
            provs = _row_provs(rows, para)
            if single:
                item = _add_text(self.doc, r, label, para.text, provs[0])
            else:
                item = self.doc.add_text(label=label, text=para.text, prov=provs[0], content_layer=_layer(label))
            item.prov.extend(provs[1:])
            if para.open_end and label == DocItemLabel.TEXT:
                self.open = (item, para, m)


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


def to_markdown(doc_or_t, furniture: bool = False) -> str:
    """Markdown with Docling's defaults, tables with spanning cells as HTML; page headers and footers
    only with ``furniture``."""
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer, MarkdownParams

    doc = load_docling(doc_or_t) if isinstance(doc_or_t, Transcription) else doc_or_t
    return MarkdownDocSerializer(doc=doc, table_serializer=_span_aware_table_serializer(),
                                 params=MarkdownParams(layers=_layers(furniture))).serialize().text


def to_text(doc_or_t, furniture: bool = False) -> str:
    """Docling's plain-text export; page headers and footers only with ``furniture``."""
    doc = load_docling(doc_or_t) if isinstance(doc_or_t, Transcription) else doc_or_t
    return doc.export_to_text(included_content_layers=_layers(furniture))
