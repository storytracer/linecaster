"""A DoclingDocument read as a transcription (a ground truth's import, the ``docling`` extra): regions with roles and
boxes, lines, heading levels, tables, the annotator and the source."""
from __future__ import annotations

import pytest

pytest.importorskip("docling_core")

from linecaster.formats.docling import from_docling  # noqa: E402


def _box(l, t, r, b):
    from docling_core.types.doc import BoundingBox, CoordOrigin

    return BoundingBox(l=l, t=t, r=r, b=b, coord_origin=CoordOrigin.TOPLEFT)


def _prov(l, t, r, b, text=""):
    from docling_core.types.doc import ProvenanceItem

    return ProvenanceItem(page_no=1, bbox=_box(l, t, r, b), charspan=(0, len(text)))


def page():
    """A DoclingDocument of one page: a running head, a title, a paragraph, a picture, a footnote."""
    from docling_core.types.doc import ContentLayer, DocItemLabel, DoclingDocument, Size

    d = DoclingDocument(name="p1")
    d.add_page(page_no=1, size=Size(width=1600, height=2400))
    d.add_text(label=DocItemLabel.PAGE_HEADER, text="12 THE HEAD", prov=_prov(120, 80, 1480, 140, "12 THE HEAD"),
               content_layer=ContentLayer.FURNITURE)
    d.add_title(text="A Title", prov=_prov(200, 200, 1400, 300, "A Title"))
    d.add_text(label=DocItemLabel.TEXT, text="First line\nsecond line", prov=_prov(200, 400, 1400, 600))
    d.add_picture(prov=_prov(200, 700, 1400, 1500))
    d.add_text(label=DocItemLabel.FOOTNOTE, text="1 A note.", prov=_prov(200, 2200, 1400, 2260))
    return d


def test_a_page_reads_with_its_roles_boxes_and_text():
    g = from_docling(page(), page_no=1, ground_truth=True, dataset="example.org/gt@0123abc", record="p1")
    assert g.source.kind == "ground_truth" and g.source.dataset == "example.org/gt@0123abc"
    assert g.annotators[0].kind == "human" and g.annotators[0].name == "docling"
    assert [g.role(r.id) for r in g.regions] == ["header", "title", "paragraph", "picture", "footnote"]
    assert g.regions[0].box == [120.0, 80.0, 1360.0, 60.0]
    assert [g.text_of(ln) for ln in g.ordered_lines()] == ["12 THE HEAD", "A Title", "First line", "second line",
                                                           "1 A note."]


def test_a_file_without_ground_truth_is_converted_and_a_table_reads():
    from docling_core.types.doc import DoclingDocument, TableCell, TableData

    d = DoclingDocument(name="p")
    cells = [TableCell(text=x, start_row_offset_idx=0, end_row_offset_idx=1, start_col_offset_idx=k,
                       end_col_offset_idx=k + 1) for k, x in enumerate("ab")]
    d.add_table(data=TableData(table_cells=cells, num_rows=1, num_cols=2))
    g = from_docling(d.export_to_dict())
    assert g.source.kind == "converted" and g.annotators[0].kind == "file"
    table = g.table(g.regions[0].id)
    assert [c.text for c in table.cells] == ["a", "b"] and [g.text_of(ln) for ln in g.lines] == ["a b"]
