"""Document assembly: a ``Transcription``'s regions, lines and tables -> its ``docling`` part (a
``DoclingDocument``), and the Markdown and text exports of it.

Ported from squiddleocr's ``document.py`` (``DocumentBuilder``, main ``7c8a052``), the ``--text lines``
mode: one Docling item per region, in reading order (regions without an order last, in list order),
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

Empty regions produce no item. Pages are numbered 1 (one document per page; a book-level document
is a later block). Reflow (paragraphs, dehyphenation, continuation across regions) is not ported yet:
``linecaster.text`` has the readable variants.
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
    grouped: dict[int, list[Line]] = {}
    for ln in lines:
        grouped.setdefault(ln.row, []).append(ln)
    return "\n".join(" ".join(ln.text for ln in grouped[k] if ln.text) for k in sorted(grouped))


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


def build_docling(t: Transcription, name: str = "page", width: int | None = None, height: int | None = None):
    """The ``DoclingDocument`` of one page (see the module docstring). ``width``/``height``: the page
    image's size (default: ``t.source.image_width``/``image_height``)."""
    from docling_core.types.doc import ContentLayer, DocItemLabel, DoclingDocument, Size

    doc = DoclingDocument(name=name)
    w, h = width or t.source.image_width, height or t.source.image_height
    if w and h:
        doc.add_page(page_no=1, size=Size(width=w, height=h))
    by_region: dict[str, list[Line]] = {}
    for ln in t.lines:
        by_region.setdefault(ln.region_id, []).append(ln)
    regions: list[Region] = sorted(t.regions, key=lambda r: r.reading_order if r.reading_order is not None else 1 << 30)
    for r in regions:
        b = bbox_of(r.polygon)
        text = region_text(by_region.get(r.id, []))
        formula, table = r.extra.get("formula"), r.extra.get("table")
        if formula is not None:
            if formula.strip():
                doc.add_text(label=DocItemLabel.FORMULA, text=formula, prov=_prov(b, formula))
        elif table is not None:
            doc.add_table(data=_table_data(table), prov=_prov(b))
        elif r.label in TEXT_LABELS:
            if not text.strip():
                continue
            label = DocItemLabel(TEXT_LABELS[r.label])
            if label == DocItemLabel.TITLE:
                doc.add_title(text=text, prov=_prov(b, text))
            elif label == DocItemLabel.SECTION_HEADER:
                doc.add_heading(text=text, prov=_prov(b, text), level=r.heading_level or 1)
            else:
                layer = ContentLayer.FURNITURE if r.label in FURNITURE else None
                doc.add_text(label=label, text=text, prov=_prov(b, text), content_layer=layer)
        else:
            pic = doc.add_picture(prov=_prov(b))
            if text.strip():
                doc.add_text(label=DocItemLabel.TEXT, text=text, prov=_prov(b, text), parent=pic)
    return doc


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
