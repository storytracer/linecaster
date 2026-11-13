"""The page/2 helpers of ``linecaster.formats.docling`` the legacy builder (``legacy_builder``) composes with, as they
were at linecaster 0.7.4, and ``page2``: a page/3 transcription in the page/2 shape they read (``Line.region_id``,
``row``, ``text``, ``bbox``; ``Region.label`` the Docling label, ``raw_label``, ``reading_order``, ``heading_level``,
``extra["table"]`` and ``extra["formula"]``). Kept verbatim as the reference of ``test_recomposition_parity.py``."""
from __future__ import annotations

from types import SimpleNamespace

from linecaster.data.geometry import BBox, bbox_of
from linecaster.data.transcription import Transcription
from linecaster.text.recomposition import Row

TEXT_LABELS = {
    "text": "text", "paragraph": "text", "title": "title", "section_header": "section_header",
    "caption": "caption", "footnote": "footnote", "page_header": "page_header", "page_footer": "page_footer",
    "list_item": "list_item", "formula": "formula", "code": "code", "reference": "reference",
    "document_index": "document_index",
}


def line_bbox(ln) -> BBox:
    if ln.polygon:
        return bbox_of(ln.polygon)
    x, y, w, h = ln.bbox
    return BBox(x, y, x + w, y + h)


def region_rows(lines):
    """The region's visual rows (``recomposition.Row``): text of the lines on each row joined with a space,
    the row's box the union of their boxes, in row order."""
    grouped: dict[int, list] = {}
    for ln in lines:
        grouped.setdefault(ln.row, []).append(ln)
    out = []
    for i, k in enumerate(sorted(grouped)):
        boxes = [line_bbox(ln) for ln in grouped[k]]
        b = BBox(min(x.x0 for x in boxes), min(x.y0 for x in boxes), max(x.x1 for x in boxes), max(x.y1 for x in boxes))
        out.append(Row(" ".join(ln.text for ln in grouped[k] if ln.text), b, i))
    return out


def region_text(lines) -> str:
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


def _layer(label):
    from docling_core.types.doc import ContentLayer, DocItemLabel

    return ContentLayer.FURNITURE if label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER) else None


def page2(t: Transcription) -> SimpleNamespace:
    """``t`` as the page/2 objects the legacy builder reads: each line's region, row, reading rank and text as
    written, each region's Docling label, raw label, rank, heading level, table (as page/2's dict) and formula."""
    ranks, rows, line_ranks = t.region_ranks(), t.rows(), t.line_ranks()
    lines = [SimpleNamespace(id=ln.id, region_id=t.region_of(ln), row=rows.get(ln.id, 0), reading_order=line_ranks[ln.id],
                             text=t.text_of(ln), polygon=ln.polygon, bbox=ln.box) for ln in t.lines]
    regions = []
    for r in t.regions:
        extra = {}
        table, formula = t.table(r.id), t.formula(r.id)
        if table is not None:
            extra["table"] = {"num_rows": table.num_rows, "num_cols": table.num_cols, "html": table.html, "cells": [
                {"text": c.text, "row": c.start_row, "col": c.start_col, "row_span": c.row_span, "col_span": c.col_span,
                 "bbox": c.box, "header": c.column_header} for c in table.cells]}
        if formula is not None:
            extra["formula"] = formula.latex
        regions.append(SimpleNamespace(id=r.id, label=t.label(r.id), raw_label=r.label, polygon=r.polygon, bbox=r.box,
                                       reading_order=ranks.get(r.id), heading_level=t.heading_level(r.id), extra=extra))
    return SimpleNamespace(lines=lines, regions=regions, source=t.source)
